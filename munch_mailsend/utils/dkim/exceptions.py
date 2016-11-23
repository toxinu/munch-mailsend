class DKIMException(Exception):
    """Base class for DKIM errors."""
    pass


class InternalError(DKIMException):
    """Internal error in dkim module. Should never happen."""
    pass


class KeyFormatError(DKIMException):
    """Key format error while parsing an RSA public or private key."""
    pass


class MessageFormatError(DKIMException):
    """RFC822 message format error."""
    pass


class ParameterError(DKIMException):
    """Input parameter error."""
    pass


class ValidationError(DKIMException):
    """Validation error."""
    pass


class InvalidCanonicalizationPolicyError(Exception):
    """The c= value could not be parsed."""
    pass


class InvalidTagValueList(Exception):
    pass


class DuplicateTag(InvalidTagValueList):
    pass


class InvalidTagSpec(InvalidTagValueList):
    pass
