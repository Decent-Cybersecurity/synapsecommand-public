// Independent layout check using OpenRTI primitive/fixed-record helpers.
// Deliberately does not use the unimplemented HLAvariantRecord helper.
#include <RTI/encoding/BasicDataElements.h>
#include <RTI/encoding/HLAfixedRecord.h>
#include <RTI/VariableLengthData.h>
#include <iostream>
#include <iomanip>
using namespace rti1516e;
static HLAfixedRecord triple32(float x,float y,float z) {
  HLAfixedRecord r; r.appendElement(HLAfloat32BE(x));
  r.appendElement(HLAfloat32BE(y)); r.appendElement(HLAfloat32BE(z));return r;
}
int main() {
 for(int a=1;a<=9;++a) {
  HLAfixedRecord xyz;xyz.appendElement(HLAfloat64BE(6378137.0));
  xyz.appendElement(HLAfloat64BE(0.0));xyz.appendElement(HLAfloat64BE(0.0));
  HLAfixedRecord body;body.appendElement(xyz);body.appendElement(HLAoctet(Octet(0)));
  body.appendElement(triple32(0,0,0));
  if(a!=1) body.appendElement(triple32(0,10,0));
  if(a==4||a==5||a==8||a==9) body.appendElement(triple32(1,2,3));
  if(a==3||a==4||a==7||a==8) body.appendElement(triple32(.25,.5,.75));
  // The selected fixed record has alignment 8. A one-octet discriminant
  // followed by this record has the profile's variant encoding.
  HLAfixedRecord selected;selected.appendElement(HLAoctet(Octet(a)));
  selected.appendElement(body);auto bytes=selected.encode();
  std::cout<<std::dec<<a<<" ";
  const auto* p=static_cast<const unsigned char*>(bytes.data());
  for(size_t i=0;i<bytes.size();++i)std::cout<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(p[i]);
  std::cout<<"\n";
 }
}
