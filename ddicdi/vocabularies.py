"""Controlled vocabularies for the dataset description.

Mode of collection and sampling procedure are the DDI Alliance vocabularies, as
published by the CESSDA vocabulary service (2026-10-27); each term keeps the concept
URI of the version that introduced it. Contributor roles are the DataCite
``contributorType`` values.
"""

from __future__ import annotations

from typing import NamedTuple


class Term(NamedTuple):
    code: str
    label: str
    uri: str


MODE_OF_COLLECTION_SET = "http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/5.0.1"
MODE_OF_COLLECTION = (
    Term('Interview', 'Interview', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/cb20d17'),
    Term('Interview.FaceToFace', 'Face-to-face interview', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/9f669a4'),
    Term('Interview.FaceToFace.CAPIorCAMI', 'Face-to-face interview: Computer-assisted (CAPI/CAMI)', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/89e4fb4'),
    Term('Interview.FaceToFace.PAPI', 'Face-to-face interview: Paper-and-pencil (PAPI)', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/e477963'),
    Term('Interview.Telephone', 'Telephone interview', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/ae68e25'),
    Term('Interview.Telephone.CATI', 'Telephone interview: Computer-assisted (CATI)', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/1498dd4'),
    Term('Interview.Email', 'E-mail interview', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/b0b2868'),
    Term('Interview.WebBased', 'Web-based interview', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/1af2bfa'),
    Term('SelfAdministeredQuestionnaire', 'Self-administered questionnaire', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/35e4248'),
    Term('SelfAdministeredQuestionnaire.Email', 'Self-administered questionnaire: E-mail', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/69a46ca'),
    Term('SelfAdministeredQuestionnaire.Paper', 'Self-administered questionnaire: Paper', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/6255fce'),
    Term('SelfAdministeredQuestionnaire.SMSorMMS', 'Self-administered questionnaire: Messaging (SMS/MMS)', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/ddaefe8'),
    Term('SelfAdministeredQuestionnaire.CAWI', 'Self-administered questionnaire: Web-based (CAWI)', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/557586d'),
    Term('SelfAdministeredQuestionnaire.CASI', 'Self-administered questionnaire: Computer-assisted (CASI)', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/e48ace5'),
    Term('FocusGroup', 'Focus group', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/9ec957d'),
    Term('FocusGroup.FaceToFace', 'Face-to-face focus group', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/00b3692'),
    Term('FocusGroup.Telephone', 'Telephone focus group', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/2b4ef44'),
    Term('FocusGroup.Online', 'Online focus group', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/4da1255'),
    Term('SelfAdministeredWritingsAndDiaries', 'Self-administered writings and/or diaries', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/08e658a'),
    Term('SelfAdministeredWritingsAndDiaries.Email', 'Self-administered writings and/or diaries: E-mail', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/fe226ad'),
    Term('SelfAdministeredWritingsAndDiaries.Paper', 'Self-administered writings and/or diaries: Paper', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/e5bef42'),
    Term('SelfAdministeredWritingsAndDiaries.WebBased', 'Self-administered writings and/or diaries: Web-based', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/9e67a7c'),
    Term('Observation', 'Observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/c680d43'),
    Term('Observation.Field', 'Field observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/bdc4aac'),
    Term('Observation.Field.Participant', 'Participant field observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/3cee522'),
    Term('Observation.Field.Nonparticipant', 'Non-participant field observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/8245871'),
    Term('Observation.Laboratory', 'Laboratory observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/e679c7f'),
    Term('Observation.Laboratory.Participant', 'Participant laboratory observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/2a58349'),
    Term('Observation.Laboratory.Nonparticipant', 'Non-participant laboratory observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/68b02fb'),
    Term('Observation.ComputerBased', 'Computer-based observation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/40b8b0c'),
    Term('Experiment', 'Experiment', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/05aeba4'),
    Term('Experiment.Laboratory', 'Laboratory experiment', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/28a60a6'),
    Term('Experiment.FieldIntervention', 'Field/Intervention experiment', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/5ff61de'),
    Term('Experiment.WebBased', 'Web-based experiment', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/ed0d083'),
    Term('Recording', 'Recording', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/c5564d2'),
    Term('Recording.RemoteSensing', 'Recording: Remote sensing', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/f25ffb0'),
    Term('AutomatedDataExtraction', 'Automated data extraction', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/c867d80'),
    Term('AutomatedDataExtraction.ApiQuery', 'Automated data extraction: API query', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/0998f59'),
    Term('AutomatedDataExtraction.DatabaseQuery', 'Automated data extraction: Database query', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/613d44d'),
    Term('AutomatedDataExtraction.WebScraping', 'Automated data extraction: Web scraping', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/d759f9a'),
    Term('ContentCoding', 'Content coding', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/4848ed5'),
    Term('Transcription', 'Transcription', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/df9aac3'),
    Term('CompilationSynthesis', 'Compilation/Synthesis', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/6decc77'),
    Term('Summary', 'Summary', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/2906121'),
    Term('Aggregation', 'Aggregation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/d9ceca6'),
    Term('Simulation', 'Simulation', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/4f502b5'),
    Term('MeasurementsAndTests', 'Measurements and tests', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/38ceaa4'),
    Term('MeasurementsAndTests.Educational', 'Educational measurements and tests', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/4b9776b'),
    Term('MeasurementsAndTests.Physical', 'Physical measurements and tests', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/c2a25a6'),
    Term('MeasurementsAndTests.Psychological', 'Psychological measurements and tests', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/27daf03'),
    Term('Other', 'Other', 'http://rdf-vocabulary.ddialliance.org/cv/ModeOfCollection/4.0.0/6311ae1'),
)

SAMPLING_PROCEDURE_SET = "http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/2.0.2"
SAMPLING_PROCEDURE = (
    Term('TotalUniverseCompleteEnumeration', 'Total universe/Complete enumeration', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/885b553'),
    Term('Probability', 'Probability', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/0d2765b'),
    Term('Probability.SimpleRandom', 'Probability: Simple random', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/38e8e88'),
    Term('Probability.SystematicRandom', 'Probability: Systematic random', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/f189f62'),
    Term('Probability.Stratified', 'Probability: Stratified', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/55d038d'),
    Term('Probability.Stratified.Proportional', 'Probability: Stratified: Proportional', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/7653f19'),
    Term('Probability.Stratified.Disproportional', 'Probability: Stratified: Disproportional', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/2059a2b'),
    Term('Probability.Cluster', 'Probability: Cluster', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/1f6e5f3'),
    Term('Probability.Cluster.SimpleRandom', 'Probability: Cluster: Simple random', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/8e08217'),
    Term('Probability.Cluster.StratifiedRandom', 'Probability: Cluster: Stratified random', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/49f4571'),
    Term('Probability.Multistage', 'Probability: Multistage', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/f91d8ca'),
    Term('Nonprobability', 'Non-probability', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/4d8364f'),
    Term('Nonprobability.Availability', 'Non-probability: Availability', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/90cbfe9'),
    Term('Nonprobability.Purposive', 'Non-probability: Purposive', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/45d8ec9'),
    Term('Nonprobability.Quota', 'Non-probability: Quota', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/f620230'),
    Term('Nonprobability.RespondentAssisted', 'Non-probability: Respondent-assisted', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/086e080'),
    Term('MixedProbabilityNonprobability', 'Mixed probability and non-probability', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/e890a15'),
    Term('Other', 'Other', 'http://rdf-vocabulary.ddialliance.org/cv/SamplingProcedure/1.1.0/6311ae1'),
)

CONTRIBUTOR_ROLE_SET = "https://schema.datacite.org/meta/kernel-4/"
# No per-term URI: a role is named by its code in the DataCite schema.
CONTRIBUTOR_ROLES = (
    Term('ContactPerson', 'Contact person', ""),
    Term('DataCollector', 'Data collector', ""),
    Term('DataCurator', 'Data curator', ""),
    Term('DataManager', 'Data manager', ""),
    Term('Distributor', 'Distributor', ""),
    Term('Editor', 'Editor', ""),
    Term('HostingInstitution', 'Hosting institution', ""),
    Term('Producer', 'Producer', ""),
    Term('ProjectLeader', 'Project leader', ""),
    Term('ProjectManager', 'Project manager', ""),
    Term('ProjectMember', 'Project member', ""),
    Term('RegistrationAgency', 'Registration agency', ""),
    Term('RegistrationAuthority', 'Registration authority', ""),
    Term('RelatedPerson', 'Related person', ""),
    Term('Researcher', 'Researcher', ""),
    Term('ResearchGroup', 'Research group', ""),
    Term('RightsHolder', 'Rights holder', ""),
    Term('Sponsor', 'Sponsor', ""),
    Term('Supervisor', 'Supervisor', ""),
    Term('Translator', 'Translator', ""),
    Term('WorkPackageLeader', 'Work package leader', ""),
    Term('Other', 'Other', ""),
)


def find(terms: tuple[Term, ...], code: str) -> Term | None:
    return next((t for t in terms if t.code == code), None)


def as_json() -> dict[str, list[dict[str, str]]]:
    """The vocabularies for the editor's dropdowns."""
    return {
        "mode_of_collection": [t._asdict() for t in MODE_OF_COLLECTION],
        "sampling_procedure": [t._asdict() for t in SAMPLING_PROCEDURE],
        "contributor_role": [t._asdict() for t in CONTRIBUTOR_ROLES],
    }

