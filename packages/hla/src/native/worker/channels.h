// The worker's two output channels (SPEC:275-279, NAT-09, NAT-15).
//
// stdout carries worker frames, one per line, written by a writer thread of their own from a
// bounded queue, so that a host that reads slowly never stalls the thread that dispatches RTI
// callbacks; the kernel pipe is flow control, not the bound (R41). fd 3 carries status records:
// a stage record before each potentially blocking RTI call, `running` after it returns, and one
// failure record per terminal condition. A write that fails (EPIPE: the reader has gone; the
// worker ignores SIGPIPE) breaks its channel for good, which the event loop treats as the end.
#ifndef SC_HLA_CHANNELS_H
#define SC_HLA_CHANNELS_H

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "record.h"

namespace sc_hla {

// Writes all of `data` to `fd`, retrying after EINTR and short writes. False on any other
// failure.
bool write_all(int fd, const std::string& data);

class StatusChannel {
 public:
  explicit StatusChannel(int fd);
  StatusChannel(const StatusChannel&) = delete;
  StatusChannel& operator=(const StatusChannel&) = delete;

  // One stage record (worker-status.schema.json): connect, join, resolve, request_update,
  // resign, disconnect or running. False when the channel is broken.
  bool stage(const char* name);
  // One failure record; `code` is one of OPS-30's and `message` fixed ASCII text within R37's
  // 1024 bytes. False when the channel is broken.
  bool failure(const std::string& code, const std::string& message);
  bool broken() const;

 private:
  bool write_line(const std::string& line);

  mutable std::mutex mutex_;
  int fd_;
  bool broken_ = false;
};

// The bounded callback queue of SPEC:279 and its writer thread.
//
// The bound covers every record a callback has accepted and the writer has not yet written:
// the event loop's batch (records wait there until the RTI's evoke call returns and their
// attribute names are known, NAT-06), the queue proper, and the one record being written. A
// record counts one frame and `queue_bytes` bytes: the variable-length data it copied (attribute
// values, tag, logical time and its implementation name, object name, federation name,
// diagnostic message); fixed members and names the event loop adds later are not counted.
// Room is reserved before a record is appended (R41: counts before appending), so the bound is
// never passed, and a record that does not fit is refused, never anything already accepted.
class FrameQueue {
 public:
  explicit FrameQueue(int fd);
  ~FrameQueue();
  FrameQueue(const FrameQueue&) = delete;
  FrameQueue& operator=(const FrameQueue&) = delete;

  void start();
  // Reserves room for one record of `bytes`. False, with nothing reserved, when the record
  // would pass 4096 frames or 16 MiB.
  bool reserve(std::size_t bytes);
  // Gives back the room of a reserved record that will never be handed over.
  void release(std::size_t bytes);
  // Moves reserved records to the writer, in order. `records` is left empty.
  void hand_over(std::vector<Record>* records);
  // Returns once every handed-over record has been written, or the channel broke.
  void wait_drained();
  // Lets the writer finish what it holds, then joins it.
  void finish();
  bool broken() const;
  // Frames and bytes currently reserved (for the harness's checks).
  std::size_t frames() const;
  std::size_t bytes() const;

 private:
  void run();

  int fd_;
  mutable std::mutex mutex_;
  std::condition_variable wake_;
  std::condition_variable drained_;
  std::deque<Record> queue_;
  std::size_t frames_ = 0;
  std::size_t bytes_ = 0;
  bool in_flight_ = false;
  bool closing_ = false;
  bool broken_ = false;
  std::thread thread_;
};

}  // namespace sc_hla

#endif  // SC_HLA_CHANNELS_H
