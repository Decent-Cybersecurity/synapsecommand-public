// Local reference-resource check, not a SynapseCommand adapter implementation.
#include <RTI/RTIambassadorFactory.h>
#include <RTI/RTIambassador.h>
#include <RTI/NullFederateAmbassador.h>
#include <iostream>
#include <string>
#include <vector>
int main(int argc,char**argv) {
 if(argc!=3){std::cerr<<"usage: reference_fom_check rti://127.0.0.1:PORT FOM_DIRECTORY\n";return 2;}
 try {
  std::string url=argv[1],dir=argv[2];
  std::wstring wurl(url.begin(),url.end()),wdir(dir.begin(),dir.end());
  rti1516e::NullFederateAmbassador fa;rti1516e::RTIambassadorFactory factory;
  auto rti=factory.createRTIambassador();rti->connect(fa,rti1516e::HLA_EVOKED,wurl);
  std::vector<std::wstring> modules;
  for(auto name:{L"Foundation",L"Enumerations",L"Base",L"Physical",L"Switches"})
   modules.push_back(wdir+L"/RPR-"+name+L"_v2.0.xml");
  const std::wstring federation=L"SC_REFERENCE_FOM_CHECK";
  rti->createFederationExecution(federation,modules,L"HLAfloat64Time");
  rti->joinFederationExecution(L"CHECKER",L"ReferenceChecker",federation);
  auto physical=rti->getObjectClassHandle(L"HLAobjectRoot.BaseEntity.PhysicalEntity");
  rti1516e::AttributeHandleSet attrs;
  for(auto name:{L"EntityIdentifier",L"EntityType",L"Spatial",L"ForceIdentifier"})
   attrs.insert(rti->getAttributeHandle(physical,name));
  rti->subscribeObjectClassAttributes(physical,attrs,true);
  rti->resignFederationExecution(rti1516e::NO_ACTION);
  rti->destroyFederationExecution(federation);rti->disconnect();
  std::cout<<"PASS: five modules load; PhysicalEntity and four attributes resolve; subscribe and cleanup succeed\n";
 }catch(const rti1516e::Exception&e){std::wcerr<<e.what()<<L"\n";return 1;}
}
