#include "channels.h"

#include <cerrno>
#include <unistd.h>

#include <utility>

#include "constants.h"
#include "text.h"

namespace sc_hla {

bool write_all(int fd, const std::string& data) {
  const char* cursor = data.data();
  std::size_t left = data.size();
  while (left > 0) {
    const ssize_t written = ::write(fd, cursor, left);
    if (written < 0) {
      if (errno == EINTR) continue;
      return false;
    }
    cursor += written;
    left -= static_cast<std::size_t>(written);
  }
  return true;
}

StatusChannel::StatusChannel(int fd) : fd_(fd) {}

bool StatusChannel::write_line(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (broken_) return false;
  if (!write_all(fd_, line)) broken_ = true;
  return !broken_;
}

bool StatusChannel::stage(const char* name) {
  std::string line = "{\"stage\":";
  append_json_string(&line, name);
  line.append(",\"type\":\"stage\"}\n");
  return write_line(line);
}

bool StatusChannel::failure(const std::string& code, const std::string& message) {
  std::string line = "{\"code\":";
  append_json_string(&line, code);
  line.append(",\"message\":");
  append_json_string(&line, message);
  line.append(",\"type\":\"failure\"}\n");
  return write_line(line);
}

bool StatusChannel::broken() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return broken_;
}

FrameQueue::FrameQueue(int fd) : fd_(fd) {}

FrameQueue::~FrameQueue() { finish(); }

void FrameQueue::start() { thread_ = std::thread(&FrameQueue::run, this); }

bool FrameQueue::reserve(std::size_t bytes) {
  std::lock_guard<std::mutex> lock(mutex_);
  // Both sums are compared without being formed past the bound (R41: check size before
  // arithmetic): `bytes` is at most a few times the per-field limits.
  if (frames_ >= kMaxQueueFrames) return false;
  if (bytes > kMaxQueueBytes - bytes_) return false;
  frames_ += 1;
  bytes_ += bytes;
  return true;
}

void FrameQueue::release(std::size_t bytes) {
  std::lock_guard<std::mutex> lock(mutex_);
  frames_ -= 1;
  bytes_ -= bytes;
}

void FrameQueue::hand_over(std::vector<Record>* records) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    for (Record& record : *records) {
      if (broken_) {
        // Nobody can read these any more; the event loop ends on the broken channel.
        frames_ -= 1;
        bytes_ -= record.queue_bytes;
      } else {
        queue_.push_back(std::move(record));
      }
    }
  }
  records->clear();
  wake_.notify_one();
}

void FrameQueue::wait_drained() {
  std::unique_lock<std::mutex> lock(mutex_);
  drained_.wait(lock, [this] { return broken_ || (queue_.empty() && !in_flight_); });
}

void FrameQueue::finish() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    closing_ = true;
  }
  wake_.notify_one();
  if (thread_.joinable()) thread_.join();
}

bool FrameQueue::broken() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return broken_;
}

std::size_t FrameQueue::frames() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return frames_;
}

std::size_t FrameQueue::bytes() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return bytes_;
}

void FrameQueue::run() {
  for (;;) {
    Record record;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      wake_.wait(lock, [this] { return !queue_.empty() || closing_; });
      if (queue_.empty()) return;
      record = std::move(queue_.front());
      queue_.pop_front();
      in_flight_ = true;
    }
    // Serialized here, in callback order, off the event loop's thread (SPEC:279).
    std::string line = serialize(record);
    line.push_back('\n');
    const bool written = write_all(fd_, line);
    {
      std::lock_guard<std::mutex> lock(mutex_);
      in_flight_ = false;
      frames_ -= 1;
      bytes_ -= record.queue_bytes;
      if (!written) {
        broken_ = true;
        for (const Record& left : queue_) {
          frames_ -= 1;
          bytes_ -= left.queue_bytes;
        }
        queue_.clear();
      }
    }
    drained_.notify_all();
    if (!written) return;
  }
}

}  // namespace sc_hla
