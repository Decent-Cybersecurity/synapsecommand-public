// Every pure virtual member of rti1516e::RTIambassador in the pinned OpenRTI headers
// (include/rti1516e/RTI/RTIambassador.h of commit 814a210), one override each, in the header's
// order: 151 in all. The ten NAT-07 allows are declared here and defined in
// recording_ambassador.cpp; every other one records the call and aborts the process. Included
// inside the class body of RecordingAmbassador, nowhere else. Written from the header by a
// generator outside the tree; the compiler checks completeness (the class would be abstract
// with one override missing), the harness's tests check the allow list.
  void connect(
      rti1516e::FederateAmbassador & federateAmbassador,
      rti1516e::CallbackModel theCallbackModel,
      std::wstring const & localSettingsDesignator)
      RTI_THROW((rti1516e::ConnectionFailed, rti1516e::InvalidLocalSettingsDesignator,
                rti1516e::UnsupportedCallbackModel, rti1516e::AlreadyConnected,
                rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override;
  void disconnect()
      RTI_THROW((rti1516e::FederateIsExecutionMember, rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override;
  void createFederationExecution(std::wstring const &, std::wstring const &, std::wstring const &)
      RTI_THROW((rti1516e::CouldNotCreateLogicalTimeFactory, rti1516e::InconsistentFDD,
                rti1516e::ErrorReadingFDD, rti1516e::CouldNotOpenFDD,
                rti1516e::FederationExecutionAlreadyExists, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("createFederationExecution");
  }
  void createFederationExecution(
      std::wstring const &,
      std::vector<std::wstring> const &,
      std::wstring const &)
      RTI_THROW((rti1516e::CouldNotCreateLogicalTimeFactory, rti1516e::InconsistentFDD,
                rti1516e::ErrorReadingFDD, rti1516e::CouldNotOpenFDD,
                rti1516e::FederationExecutionAlreadyExists, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("createFederationExecution");
  }
  void createFederationExecutionWithMIM(
      std::wstring const &,
      std::vector<std::wstring> const &,
      std::wstring const &,
      std::wstring const &)
      RTI_THROW((rti1516e::CouldNotCreateLogicalTimeFactory, rti1516e::InconsistentFDD,
                rti1516e::ErrorReadingFDD, rti1516e::CouldNotOpenFDD,
                rti1516e::DesignatorIsHLAstandardMIM, rti1516e::ErrorReadingMIM,
                rti1516e::CouldNotOpenMIM, rti1516e::FederationExecutionAlreadyExists,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("createFederationExecutionWithMIM");
  }
  void destroyFederationExecution(std::wstring const &)
      RTI_THROW((rti1516e::FederatesCurrentlyJoined, rti1516e::FederationExecutionDoesNotExist,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("destroyFederationExecution");
  }
  void listFederationExecutions()
      RTI_THROW((rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("listFederationExecutions");
  }
  rti1516e::FederateHandle joinFederationExecution(
      std::wstring const &,
      std::wstring const &,
      std::vector<std::wstring> const &)
      RTI_THROW((rti1516e::CouldNotCreateLogicalTimeFactory,
                rti1516e::FederationExecutionDoesNotExist, rti1516e::InconsistentFDD,
                rti1516e::ErrorReadingFDD, rti1516e::CouldNotOpenFDD, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateAlreadyExecutionMember,
                rti1516e::NotConnected, rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override {
    forbidden("joinFederationExecution");
  }
  rti1516e::FederateHandle joinFederationExecution(
      std::wstring const & federateName,
      std::wstring const & federateType,
      std::wstring const & federationExecutionName,
      std::vector<std::wstring> const & additionalFomModules)
      RTI_THROW((rti1516e::CouldNotCreateLogicalTimeFactory, rti1516e::FederateNameAlreadyInUse,
                rti1516e::FederationExecutionDoesNotExist, rti1516e::InconsistentFDD,
                rti1516e::ErrorReadingFDD, rti1516e::CouldNotOpenFDD, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateAlreadyExecutionMember,
                rti1516e::NotConnected, rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override;
  void resignFederationExecution(rti1516e::ResignAction resignAction)
      RTI_THROW((rti1516e::InvalidResignAction, rti1516e::OwnershipAcquisitionPending,
                rti1516e::FederateOwnsAttributes, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override;
  void registerFederationSynchronizationPoint(
      std::wstring const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("registerFederationSynchronizationPoint");
  }
  void registerFederationSynchronizationPoint(
      std::wstring const &,
      rti1516e::VariableLengthData const &,
      rti1516e::FederateHandleSet const &)
      RTI_THROW((rti1516e::InvalidFederateHandle, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("registerFederationSynchronizationPoint");
  }
  void synchronizationPointAchieved(std::wstring const &, bool)
      RTI_THROW((rti1516e::SynchronizationPointLabelNotAnnounced, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("synchronizationPointAchieved");
  }
  void requestFederationSave(std::wstring const &)
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("requestFederationSave");
  }
  void requestFederationSave(std::wstring const &, rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::LogicalTimeAlreadyPassed, rti1516e::InvalidLogicalTime,
                rti1516e::FederateUnableToUseTime, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("requestFederationSave");
  }
  void federateSaveBegun()
      RTI_THROW((rti1516e::SaveNotInitiated, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("federateSaveBegun");
  }
  void federateSaveComplete()
      RTI_THROW((rti1516e::FederateHasNotBegunSave, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("federateSaveComplete");
  }
  void federateSaveNotComplete()
      RTI_THROW((rti1516e::FederateHasNotBegunSave, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("federateSaveNotComplete");
  }
  void abortFederationSave()
      RTI_THROW((rti1516e::SaveNotInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("abortFederationSave");
  }
  void queryFederationSaveStatus()
      RTI_THROW((rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("queryFederationSaveStatus");
  }
  void requestFederationRestore(std::wstring const &)
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("requestFederationRestore");
  }
  void federateRestoreComplete()
      RTI_THROW((rti1516e::RestoreNotRequested, rti1516e::SaveInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("federateRestoreComplete");
  }
  void federateRestoreNotComplete()
      RTI_THROW((rti1516e::RestoreNotRequested, rti1516e::SaveInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("federateRestoreNotComplete");
  }
  void abortFederationRestore()
      RTI_THROW((rti1516e::RestoreNotInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("abortFederationRestore");
  }
  void queryFederationRestoreStatus()
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("queryFederationRestoreStatus");
  }
  void publishObjectClassAttributes(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("publishObjectClassAttributes");
  }
  void unpublishObjectClass(rti1516e::ObjectClassHandle)
      RTI_THROW((rti1516e::OwnershipAcquisitionPending, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("unpublishObjectClass");
  }
  void unpublishObjectClassAttributes(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::OwnershipAcquisitionPending, rti1516e::AttributeNotDefined,
                rti1516e::ObjectClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("unpublishObjectClassAttributes");
  }
  void publishInteractionClass(rti1516e::InteractionClassHandle)
      RTI_THROW((rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("publishInteractionClass");
  }
  void unpublishInteractionClass(rti1516e::InteractionClassHandle)
      RTI_THROW((rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("unpublishInteractionClass");
  }
  void subscribeObjectClassAttributes(
      rti1516e::ObjectClassHandle theClass,
      rti1516e::AttributeHandleSet const & attributeList,
      bool active,
      std::wstring const & updateRateDesignator)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectClassNotDefined,
                rti1516e::InvalidUpdateRateDesignator, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override;
  void unsubscribeObjectClass(rti1516e::ObjectClassHandle)
      RTI_THROW((rti1516e::ObjectClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("unsubscribeObjectClass");
  }
  void unsubscribeObjectClassAttributes(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("unsubscribeObjectClassAttributes");
  }
  void subscribeInteractionClass(rti1516e::InteractionClassHandle, bool)
      RTI_THROW((rti1516e::FederateServiceInvocationsAreBeingReportedViaMOM,
                rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("subscribeInteractionClass");
  }
  void unsubscribeInteractionClass(rti1516e::InteractionClassHandle)
      RTI_THROW((rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("unsubscribeInteractionClass");
  }
  void reserveObjectInstanceName(std::wstring const &)
      RTI_THROW((rti1516e::IllegalName, rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("reserveObjectInstanceName");
  }
  void releaseObjectInstanceName(std::wstring const &)
      RTI_THROW((rti1516e::ObjectInstanceNameNotReserved, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("releaseObjectInstanceName");
  }
  void reserveMultipleObjectInstanceName(std::set<std::wstring> const &)
      RTI_THROW((rti1516e::IllegalName, rti1516e::NameSetWasEmpty, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("reserveMultipleObjectInstanceName");
  }
  void releaseMultipleObjectInstanceName(std::set<std::wstring> const &)
      RTI_THROW((rti1516e::ObjectInstanceNameNotReserved, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("releaseMultipleObjectInstanceName");
  }
  rti1516e::ObjectInstanceHandle registerObjectInstance(rti1516e::ObjectClassHandle)
      RTI_THROW((rti1516e::ObjectClassNotPublished, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("registerObjectInstance");
  }
  rti1516e::ObjectInstanceHandle registerObjectInstance(
      rti1516e::ObjectClassHandle,
      std::wstring const &)
      RTI_THROW((rti1516e::ObjectInstanceNameInUse, rti1516e::ObjectInstanceNameNotReserved,
                rti1516e::ObjectClassNotPublished, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("registerObjectInstance");
  }
  void updateAttributeValues(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleValueMap const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::AttributeNotOwned, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("updateAttributeValues");
  }
  rti1516e::MessageRetractionHandle updateAttributeValues(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleValueMap const &,
      rti1516e::VariableLengthData const &,
      rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::InvalidLogicalTime, rti1516e::AttributeNotOwned,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("updateAttributeValues");
  }
  void sendInteraction(
      rti1516e::InteractionClassHandle,
      rti1516e::ParameterHandleValueMap const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::InteractionClassNotPublished,
                rti1516e::InteractionParameterNotDefined, rti1516e::InteractionClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("sendInteraction");
  }
  rti1516e::MessageRetractionHandle sendInteraction(
      rti1516e::InteractionClassHandle,
      rti1516e::ParameterHandleValueMap const &,
      rti1516e::VariableLengthData const &,
      rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::InvalidLogicalTime, rti1516e::InteractionClassNotPublished,
                rti1516e::InteractionParameterNotDefined, rti1516e::InteractionClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("sendInteraction");
  }
  void deleteObjectInstance(rti1516e::ObjectInstanceHandle, rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::DeletePrivilegeNotHeld, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("deleteObjectInstance");
  }
  rti1516e::MessageRetractionHandle deleteObjectInstance(
      rti1516e::ObjectInstanceHandle,
      rti1516e::VariableLengthData const &,
      rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::InvalidLogicalTime, rti1516e::DeletePrivilegeNotHeld,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("deleteObjectInstance");
  }
  void localDeleteObjectInstance(rti1516e::ObjectInstanceHandle)
      RTI_THROW((rti1516e::OwnershipAcquisitionPending, rti1516e::FederateOwnsAttributes,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("localDeleteObjectInstance");
  }
  void requestAttributeValueUpdate(
      rti1516e::ObjectInstanceHandle theObject,
      rti1516e::AttributeHandleSet const & theAttributes,
      rti1516e::VariableLengthData const & theUserSuppliedTag)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override;
  void requestAttributeValueUpdate(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("requestAttributeValueUpdate");
  }
  void requestAttributeTransportationTypeChange(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::TransportationType)
      RTI_THROW((rti1516e::AttributeAlreadyBeingChanged, rti1516e::AttributeNotOwned,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::InvalidTransportationType, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("requestAttributeTransportationTypeChange");
  }
  void queryAttributeTransportationType(rti1516e::ObjectInstanceHandle, rti1516e::AttributeHandle)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("queryAttributeTransportationType");
  }
  void requestInteractionTransportationTypeChange(
      rti1516e::InteractionClassHandle,
      rti1516e::TransportationType)
      RTI_THROW((rti1516e::InteractionClassAlreadyBeingChanged,
                rti1516e::InteractionClassNotPublished, rti1516e::InteractionClassNotDefined,
                rti1516e::InvalidTransportationType, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("requestInteractionTransportationTypeChange");
  }
  void queryInteractionTransportationType(
      rti1516e::FederateHandle,
      rti1516e::InteractionClassHandle)
      RTI_THROW((rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("queryInteractionTransportationType");
  }
  void unconditionalAttributeOwnershipDivestiture(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeNotOwned, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("unconditionalAttributeOwnershipDivestiture");
  }
  void negotiatedAttributeOwnershipDivestiture(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::AttributeAlreadyBeingDivested, rti1516e::AttributeNotOwned,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("negotiatedAttributeOwnershipDivestiture");
  }
  void confirmDivestiture(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::NoAcquisitionPending, rti1516e::AttributeDivestitureWasNotRequested,
                rti1516e::AttributeNotOwned, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("confirmDivestiture");
  }
  void attributeOwnershipAcquisition(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::AttributeNotPublished, rti1516e::ObjectClassNotPublished,
                rti1516e::FederateOwnsAttributes, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("attributeOwnershipAcquisition");
  }
  void attributeOwnershipAcquisitionIfAvailable(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeAlreadyBeingAcquired, rti1516e::AttributeNotPublished,
                rti1516e::ObjectClassNotPublished, rti1516e::FederateOwnsAttributes,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("attributeOwnershipAcquisitionIfAvailable");
  }
  void attributeOwnershipReleaseDenied(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeNotOwned, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("attributeOwnershipReleaseDenied");
  }
  void attributeOwnershipDivestitureIfWanted(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::AttributeHandleSet &)
      RTI_THROW((rti1516e::AttributeNotOwned, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("attributeOwnershipDivestitureIfWanted");
  }
  void cancelNegotiatedAttributeOwnershipDivestiture(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeDivestitureWasNotRequested, rti1516e::AttributeNotOwned,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("cancelNegotiatedAttributeOwnershipDivestiture");
  }
  void cancelAttributeOwnershipAcquisition(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &)
      RTI_THROW((rti1516e::AttributeAcquisitionWasNotRequested, rti1516e::AttributeAlreadyOwned,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("cancelAttributeOwnershipAcquisition");
  }
  void queryAttributeOwnership(rti1516e::ObjectInstanceHandle, rti1516e::AttributeHandle)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("queryAttributeOwnership");
  }
  bool isAttributeOwnedByFederate(rti1516e::ObjectInstanceHandle, rti1516e::AttributeHandle)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("isAttributeOwnedByFederate");
  }
  void enableTimeRegulation(rti1516e::LogicalTimeInterval const &)
      RTI_THROW((rti1516e::InvalidLookahead, rti1516e::InTimeAdvancingState,
                rti1516e::RequestForTimeRegulationPending,
                rti1516e::TimeRegulationAlreadyEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableTimeRegulation");
  }
  void disableTimeRegulation()
      RTI_THROW((rti1516e::TimeRegulationIsNotEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableTimeRegulation");
  }
  void enableTimeConstrained()
      RTI_THROW((rti1516e::InTimeAdvancingState, rti1516e::RequestForTimeConstrainedPending,
                rti1516e::TimeConstrainedAlreadyEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableTimeConstrained");
  }
  void disableTimeConstrained()
      RTI_THROW((rti1516e::TimeConstrainedIsNotEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableTimeConstrained");
  }
  void timeAdvanceRequest(rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::LogicalTimeAlreadyPassed, rti1516e::InvalidLogicalTime,
                rti1516e::InTimeAdvancingState, rti1516e::RequestForTimeRegulationPending,
                rti1516e::RequestForTimeConstrainedPending, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("timeAdvanceRequest");
  }
  void timeAdvanceRequestAvailable(rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::LogicalTimeAlreadyPassed, rti1516e::InvalidLogicalTime,
                rti1516e::InTimeAdvancingState, rti1516e::RequestForTimeRegulationPending,
                rti1516e::RequestForTimeConstrainedPending, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("timeAdvanceRequestAvailable");
  }
  void nextMessageRequest(rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::LogicalTimeAlreadyPassed, rti1516e::InvalidLogicalTime,
                rti1516e::InTimeAdvancingState, rti1516e::RequestForTimeRegulationPending,
                rti1516e::RequestForTimeConstrainedPending, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("nextMessageRequest");
  }
  void nextMessageRequestAvailable(rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::LogicalTimeAlreadyPassed, rti1516e::InvalidLogicalTime,
                rti1516e::InTimeAdvancingState, rti1516e::RequestForTimeRegulationPending,
                rti1516e::RequestForTimeConstrainedPending, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("nextMessageRequestAvailable");
  }
  void flushQueueRequest(rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::LogicalTimeAlreadyPassed, rti1516e::InvalidLogicalTime,
                rti1516e::InTimeAdvancingState, rti1516e::RequestForTimeRegulationPending,
                rti1516e::RequestForTimeConstrainedPending, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("flushQueueRequest");
  }
  void enableAsynchronousDelivery()
      RTI_THROW((rti1516e::AsynchronousDeliveryAlreadyEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableAsynchronousDelivery");
  }
  void disableAsynchronousDelivery()
      RTI_THROW((rti1516e::AsynchronousDeliveryAlreadyDisabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableAsynchronousDelivery");
  }
  bool queryGALT(rti1516e::LogicalTime &)
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("queryGALT");
  }
  void queryLogicalTime(rti1516e::LogicalTime &)
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("queryLogicalTime");
  }
  bool queryLITS(rti1516e::LogicalTime &)
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("queryLITS");
  }
  void modifyLookahead(rti1516e::LogicalTimeInterval const &)
      RTI_THROW((rti1516e::InvalidLookahead, rti1516e::InTimeAdvancingState,
                rti1516e::TimeRegulationIsNotEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("modifyLookahead");
  }
  void queryLookahead(rti1516e::LogicalTimeInterval &)
      RTI_THROW((rti1516e::TimeRegulationIsNotEnabled, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("queryLookahead");
  }
  void retract(rti1516e::MessageRetractionHandle)
      RTI_THROW((rti1516e::MessageCanNoLongerBeRetracted,
                rti1516e::InvalidMessageRetractionHandle, rti1516e::TimeRegulationIsNotEnabled,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("retract");
  }
  void changeAttributeOrderType(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSet const &,
      rti1516e::OrderType)
      RTI_THROW((rti1516e::AttributeNotOwned, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("changeAttributeOrderType");
  }
  void changeInteractionOrderType(rti1516e::InteractionClassHandle, rti1516e::OrderType)
      RTI_THROW((rti1516e::InteractionClassNotPublished, rti1516e::InteractionClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("changeInteractionOrderType");
  }
  rti1516e::RegionHandle createRegion(rti1516e::DimensionHandleSet const &)
      RTI_THROW((rti1516e::InvalidDimensionHandle, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("createRegion");
  }
  void commitRegionModifications(rti1516e::RegionHandleSet const &)
      RTI_THROW((rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("commitRegionModifications");
  }
  void deleteRegion(rti1516e::RegionHandle const &)
      RTI_THROW((rti1516e::RegionInUseForUpdateOrSubscription,
                rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("deleteRegion");
  }
  rti1516e::ObjectInstanceHandle registerObjectInstanceWithRegions(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &)
      RTI_THROW((rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::AttributeNotPublished,
                rti1516e::ObjectClassNotPublished, rti1516e::AttributeNotDefined,
                rti1516e::ObjectClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("registerObjectInstanceWithRegions");
  }
  rti1516e::ObjectInstanceHandle registerObjectInstanceWithRegions(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &,
      std::wstring const &)
      RTI_THROW((rti1516e::ObjectInstanceNameInUse, rti1516e::ObjectInstanceNameNotReserved,
                rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::AttributeNotPublished,
                rti1516e::ObjectClassNotPublished, rti1516e::AttributeNotDefined,
                rti1516e::ObjectClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("registerObjectInstanceWithRegions");
  }
  void associateRegionsForUpdates(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &)
      RTI_THROW((rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::AttributeNotDefined,
                rti1516e::ObjectInstanceNotKnown, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("associateRegionsForUpdates");
  }
  void unassociateRegionsForUpdates(
      rti1516e::ObjectInstanceHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &)
      RTI_THROW((rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::AttributeNotDefined, rti1516e::ObjectInstanceNotKnown,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("unassociateRegionsForUpdates");
  }
  void subscribeObjectClassAttributesWithRegions(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &,
      bool,
      std::wstring const &)
      RTI_THROW((rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::AttributeNotDefined,
                rti1516e::ObjectClassNotDefined, rti1516e::InvalidUpdateRateDesignator,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("subscribeObjectClassAttributesWithRegions");
  }
  void unsubscribeObjectClassAttributesWithRegions(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &)
      RTI_THROW((rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::AttributeNotDefined, rti1516e::ObjectClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("unsubscribeObjectClassAttributesWithRegions");
  }
  void subscribeInteractionClassWithRegions(
      rti1516e::InteractionClassHandle,
      rti1516e::RegionHandleSet const &,
      bool)
      RTI_THROW((rti1516e::FederateServiceInvocationsAreBeingReportedViaMOM,
                rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::InteractionClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("subscribeInteractionClassWithRegions");
  }
  void unsubscribeInteractionClassWithRegions(
      rti1516e::InteractionClassHandle,
      rti1516e::RegionHandleSet const &)
      RTI_THROW((rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("unsubscribeInteractionClassWithRegions");
  }
  void sendInteractionWithRegions(
      rti1516e::InteractionClassHandle,
      rti1516e::ParameterHandleValueMap const &,
      rti1516e::RegionHandleSet const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::InteractionClassNotPublished,
                rti1516e::InteractionParameterNotDefined, rti1516e::InteractionClassNotDefined,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("sendInteractionWithRegions");
  }
  rti1516e::MessageRetractionHandle sendInteractionWithRegions(
      rti1516e::InteractionClassHandle,
      rti1516e::ParameterHandleValueMap const &,
      rti1516e::RegionHandleSet const &,
      rti1516e::VariableLengthData const &,
      rti1516e::LogicalTime const &)
      RTI_THROW((rti1516e::InvalidLogicalTime, rti1516e::InvalidRegionContext,
                rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::InteractionClassNotPublished, rti1516e::InteractionParameterNotDefined,
                rti1516e::InteractionClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("sendInteractionWithRegions");
  }
  void requestAttributeValueUpdateWithRegions(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandleSetRegionHandleSetPairVector const &,
      rti1516e::VariableLengthData const &)
      RTI_THROW((rti1516e::InvalidRegionContext, rti1516e::RegionNotCreatedByThisFederate,
                rti1516e::InvalidRegion, rti1516e::AttributeNotDefined,
                rti1516e::ObjectClassNotDefined, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("requestAttributeValueUpdateWithRegions");
  }
  rti1516e::ResignAction getAutomaticResignDirective()
      RTI_THROW((rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getAutomaticResignDirective");
  }
  void setAutomaticResignDirective(rti1516e::ResignAction)
      RTI_THROW((rti1516e::InvalidResignAction, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("setAutomaticResignDirective");
  }
  rti1516e::FederateHandle getFederateHandle(std::wstring const &)
      RTI_THROW((rti1516e::NameNotFound, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getFederateHandle");
  }
  std::wstring getFederateName(rti1516e::FederateHandle)
      RTI_THROW((rti1516e::InvalidFederateHandle, rti1516e::FederateHandleNotKnown,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getFederateName");
  }
  rti1516e::ObjectClassHandle getObjectClassHandle(std::wstring const & theName)
      RTI_THROW((rti1516e::NameNotFound, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override;
  std::wstring getObjectClassName(rti1516e::ObjectClassHandle)
      RTI_THROW((rti1516e::InvalidObjectClassHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getObjectClassName");
  }
  rti1516e::ObjectClassHandle getKnownObjectClassHandle(rti1516e::ObjectInstanceHandle)
      RTI_THROW((rti1516e::ObjectInstanceNotKnown, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getKnownObjectClassHandle");
  }
  rti1516e::ObjectInstanceHandle getObjectInstanceHandle(std::wstring const &)
      RTI_THROW((rti1516e::ObjectInstanceNotKnown, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getObjectInstanceHandle");
  }
  std::wstring getObjectInstanceName(rti1516e::ObjectInstanceHandle)
      RTI_THROW((rti1516e::ObjectInstanceNotKnown, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getObjectInstanceName");
  }
  rti1516e::AttributeHandle getAttributeHandle(
      rti1516e::ObjectClassHandle whichClass,
      std::wstring const & theAttributeName)
      RTI_THROW((rti1516e::NameNotFound, rti1516e::InvalidObjectClassHandle,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override;
  std::wstring getAttributeName(
      rti1516e::ObjectClassHandle whichClass,
      rti1516e::AttributeHandle theHandle)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::InvalidAttributeHandle,
                rti1516e::InvalidObjectClassHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override;
  double getUpdateRateValue(std::wstring const &)
      RTI_THROW((rti1516e::InvalidUpdateRateDesignator, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getUpdateRateValue");
  }
  double getUpdateRateValueForAttribute(rti1516e::ObjectInstanceHandle, rti1516e::AttributeHandle)
      RTI_THROW((rti1516e::ObjectInstanceNotKnown, rti1516e::AttributeNotDefined,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getUpdateRateValueForAttribute");
  }
  rti1516e::InteractionClassHandle getInteractionClassHandle(std::wstring const &)
      RTI_THROW((rti1516e::NameNotFound, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getInteractionClassHandle");
  }
  std::wstring getInteractionClassName(rti1516e::InteractionClassHandle)
      RTI_THROW((rti1516e::InvalidInteractionClassHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getInteractionClassName");
  }
  rti1516e::ParameterHandle getParameterHandle(
      rti1516e::InteractionClassHandle,
      std::wstring const &)
      RTI_THROW((rti1516e::NameNotFound, rti1516e::InvalidInteractionClassHandle,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getParameterHandle");
  }
  std::wstring getParameterName(rti1516e::InteractionClassHandle, rti1516e::ParameterHandle)
      RTI_THROW((rti1516e::InteractionParameterNotDefined, rti1516e::InvalidParameterHandle,
                rti1516e::InvalidInteractionClassHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getParameterName");
  }
  rti1516e::OrderType getOrderType(std::wstring const &)
      RTI_THROW((rti1516e::InvalidOrderName, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getOrderType");
  }
  std::wstring getOrderName(rti1516e::OrderType)
      RTI_THROW((rti1516e::InvalidOrderType, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getOrderName");
  }
  rti1516e::TransportationType getTransportationType(std::wstring const &)
      RTI_THROW((rti1516e::InvalidTransportationName, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getTransportationType");
  }
  std::wstring getTransportationName(rti1516e::TransportationType)
      RTI_THROW((rti1516e::InvalidTransportationType, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getTransportationName");
  }
  rti1516e::DimensionHandleSet getAvailableDimensionsForClassAttribute(
      rti1516e::ObjectClassHandle,
      rti1516e::AttributeHandle)
      RTI_THROW((rti1516e::AttributeNotDefined, rti1516e::InvalidAttributeHandle,
                rti1516e::InvalidObjectClassHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getAvailableDimensionsForClassAttribute");
  }
  rti1516e::DimensionHandleSet getAvailableDimensionsForInteractionClass(
      rti1516e::InteractionClassHandle)
      RTI_THROW((rti1516e::InvalidInteractionClassHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getAvailableDimensionsForInteractionClass");
  }
  rti1516e::DimensionHandle getDimensionHandle(std::wstring const &)
      RTI_THROW((rti1516e::NameNotFound, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getDimensionHandle");
  }
  std::wstring getDimensionName(rti1516e::DimensionHandle)
      RTI_THROW((rti1516e::InvalidDimensionHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getDimensionName");
  }
  unsigned long getDimensionUpperBound(rti1516e::DimensionHandle)
      RTI_THROW((rti1516e::InvalidDimensionHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("getDimensionUpperBound");
  }
  rti1516e::DimensionHandleSet getDimensionHandleSet(rti1516e::RegionHandle)
      RTI_THROW((rti1516e::InvalidRegion, rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getDimensionHandleSet");
  }
  rti1516e::RangeBounds getRangeBounds(rti1516e::RegionHandle, rti1516e::DimensionHandle)
      RTI_THROW((rti1516e::RegionDoesNotContainSpecifiedDimension, rti1516e::InvalidRegion,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getRangeBounds");
  }
  void setRangeBounds(
      rti1516e::RegionHandle,
      rti1516e::DimensionHandle,
      rti1516e::RangeBounds const &)
      RTI_THROW((rti1516e::InvalidRangeBound, rti1516e::RegionDoesNotContainSpecifiedDimension,
                rti1516e::RegionNotCreatedByThisFederate, rti1516e::InvalidRegion,
                rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("setRangeBounds");
  }
  unsigned long normalizeFederateHandle(rti1516e::FederateHandle)
      RTI_THROW((rti1516e::InvalidFederateHandle, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("normalizeFederateHandle");
  }
  unsigned long normalizeServiceGroup(rti1516e::ServiceGroup)
      RTI_THROW((rti1516e::InvalidServiceGroup, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("normalizeServiceGroup");
  }
  void enableObjectClassRelevanceAdvisorySwitch()
      RTI_THROW((rti1516e::ObjectClassRelevanceAdvisorySwitchIsOn, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableObjectClassRelevanceAdvisorySwitch");
  }
  void disableObjectClassRelevanceAdvisorySwitch()
      RTI_THROW((rti1516e::ObjectClassRelevanceAdvisorySwitchIsOff, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableObjectClassRelevanceAdvisorySwitch");
  }
  void enableAttributeRelevanceAdvisorySwitch()
      RTI_THROW((rti1516e::AttributeRelevanceAdvisorySwitchIsOn, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableAttributeRelevanceAdvisorySwitch");
  }
  void disableAttributeRelevanceAdvisorySwitch()
      RTI_THROW((rti1516e::AttributeRelevanceAdvisorySwitchIsOff, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableAttributeRelevanceAdvisorySwitch");
  }
  void enableAttributeScopeAdvisorySwitch()
      RTI_THROW((rti1516e::AttributeScopeAdvisorySwitchIsOn, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableAttributeScopeAdvisorySwitch");
  }
  void disableAttributeScopeAdvisorySwitch()
      RTI_THROW((rti1516e::AttributeScopeAdvisorySwitchIsOff, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableAttributeScopeAdvisorySwitch");
  }
  void enableInteractionRelevanceAdvisorySwitch()
      RTI_THROW((rti1516e::InteractionRelevanceAdvisorySwitchIsOn, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("enableInteractionRelevanceAdvisorySwitch");
  }
  void disableInteractionRelevanceAdvisorySwitch()
      RTI_THROW((rti1516e::InteractionRelevanceAdvisorySwitchIsOff, rti1516e::SaveInProgress,
                rti1516e::RestoreInProgress, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("disableInteractionRelevanceAdvisorySwitch");
  }
  bool evokeCallback(double)
      RTI_THROW((rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override {
    forbidden("evokeCallback");
  }
  bool evokeMultipleCallbacks(
      double approximateMinimumTimeInSeconds,
      double approximateMaximumTimeInSeconds)
      RTI_THROW((rti1516e::CallNotAllowedFromWithinCallback,
                rti1516e::RTIinternalError)) override;
  void enableCallbacks()
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::RTIinternalError)) override {
    forbidden("enableCallbacks");
  }
  void disableCallbacks()
      RTI_THROW((rti1516e::SaveInProgress, rti1516e::RestoreInProgress,
                rti1516e::RTIinternalError)) override {
    forbidden("disableCallbacks");
  }
  RTI_UNIQUE_PTR<rti1516e::LogicalTimeFactory> getTimeFactory() const
      RTI_THROW((rti1516e::FederateNotExecutionMember, rti1516e::NotConnected,
                rti1516e::RTIinternalError)) override {
    forbidden("getTimeFactory");
  }
  rti1516e::FederateHandle decodeFederateHandle(rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeFederateHandle");
  }
  rti1516e::ObjectClassHandle decodeObjectClassHandle(rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeObjectClassHandle");
  }
  rti1516e::InteractionClassHandle decodeInteractionClassHandle(
      rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeInteractionClassHandle");
  }
  rti1516e::ObjectInstanceHandle decodeObjectInstanceHandle(
      rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeObjectInstanceHandle");
  }
  rti1516e::AttributeHandle decodeAttributeHandle(rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeAttributeHandle");
  }
  rti1516e::ParameterHandle decodeParameterHandle(rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeParameterHandle");
  }
  rti1516e::DimensionHandle decodeDimensionHandle(rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeDimensionHandle");
  }
  rti1516e::MessageRetractionHandle decodeMessageRetractionHandle(
      rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeMessageRetractionHandle");
  }
  rti1516e::RegionHandle decodeRegionHandle(rti1516e::VariableLengthData const &) const
      RTI_THROW((rti1516e::CouldNotDecode, rti1516e::FederateNotExecutionMember,
                rti1516e::NotConnected, rti1516e::RTIinternalError)) override {
    forbidden("decodeRegionHandle");
  }
