class FeatureError(Exception): pass
class InvalidFeature(FeatureError): pass
class FeatureCalculationRejected(FeatureError): pass
class SnapshotPurposeMismatch(FeatureError): pass
class FeatureSetNotFound(FeatureError): pass
class RepositoryConflict(FeatureError): pass
