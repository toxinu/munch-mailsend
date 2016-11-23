import re
import time
import base64
import logging
from logging import NullHandler


from .exceptions import DKIMException
from .exceptions import KeyFormatError
from .exceptions import ParameterError
from .exceptions import ValidationError
from .exceptions import MessageFormatError
from .exceptions import InvalidTagValueList
from .utils import hash_headers
from .utils import rfc822_parse
from .utils import get_bit_size
from .utils import parse_tag_value
from .utils import validate_signature_fields
from .crypto import HASH_ALGORITHMS
from .crypto import parse_public_key
from .crypto import UnparsableKeyError
from .crypto import DigestTooLargeError
from .crypto import parse_pem_private_key
from .crypto import RSASSA_PKCS1_v1_5_sign
from .crypto import RSASSA_PKCS1_v1_5_verify
from .canonicalization import CanonicalizationPolicy
from .canonicalization import InvalidCanonicalizationPolicyError

try:
    from .dnsplug import get_txt
except:
    def get_txt(s):
        raise RuntimeError("DKIM.verify requires DNS or dnspython module")


Relaxed, Simple = 'relaxed', 'simple'


class DKIM(object):
    #: The U{RFC5322<http://tools.ietf.org/html/rfc5322#section-3.6>}
    #: complete list of singleton headers (which should
    #: appear at most once).  This can be used for a "paranoid" or
    #: "strict" signing mode.
    #: Bcc in this list is in the SHOULD NOT sign list, the rest could
    #: be in the default FROZEN list, but that could also make signatures
    #: more fragile than necessary.
    #: @since: 0.5
    RFC5322_SINGLETON = (
        b'date', b'from', b'sender', b'reply-to', b'to', b'cc',
        b'bcc', b'message-id', b'in-reply-to', b'references')

    #: Header fields to protect from additions by default.
    #:
    #: The short list below is the result more of instinct than logic.
    #: @since: 0.5
    FROZEN = (b'from', b'date', b'subject')

    #: The rfc4871 recommended header fields to sign
    #: @since: 0.5
    SHOULD = (
        b'sender', b'reply-to', b'subject', b'date', b'message-id', b'to',
        b'cc', b'mime-version', b'content-type', b'content-transfer-encoding',
        b'content-id', b'content-description', b'resent-date', b'resent-from',
        b'resent-sender', b'resent-to', b'resent-cc', b'resent-message-id',
        b'in-reply-to', b'references', b'list-id', b'list-help',
        b'list-unsubscribe', b'list-subscribe', b'list-post',
        b'list-owner', b'list-archive'
    )

    #: The rfc4871 recommended header fields not to sign.
    #: @since: 0.5
    SHOULD_NOT = (
        b'return-path', b'received', b'comments', b'keywords',
        b'bcc', b'resent-bcc', b'dkim-signature'
    )

    #: Create a DKIM instance to sign and verify rfc5322 messages.
    #:
    #: @param message: an RFC822 formatted message to be signed or verified
    #: (with either \\n or \\r\\n line endings)
    #: @param logger: a logger to which debug info
    #:                will be written (default None)
    #: @param signature_algorithm: the signing algorithm to use when signing
    def __init__(
            self, message=None, logger=None,
            signature_algorithm='rsa-sha256', minkey=1024):
        self.set_message(message)

        if logger is None:
            logger = logging.getLogger('dkimpy')
            if not logger.handlers:
                logger.addHandler(NullHandler())
        self.logger = logger

        if signature_algorithm not in HASH_ALGORITHMS:
            raise ParameterError(
                "Unsupported signature algorithm: {}".format(
                    signature_algorithm))
        self.signature_algorithm = signature_algorithm

        #: Header fields which should be signed.  Default from RFC4871
        self.should_sign = set(DKIM.SHOULD)
        #: Header fields which should not be signed.
        #: The default is from RFC4871.
        #: Attempting to sign these headers results in an exception.
        #: If it is necessary to sign one of these, it must be removed
        #: from this list first.
        self.should_not_sign = set(DKIM.SHOULD_NOT)
        #: Header fields to sign an extra time to prevent additions.
        self.frozen_sign = set(DKIM.FROZEN)
        #: Minimum public key size.  Shorter keys raise KeyFormatError. The
        #: default is 1024
        self.minkey = minkey

    def add_frozen(self, s):
        """ Add headers not in should_not_sign to frozen_sign.
        @param s: list of headers to add to frozen_sign
        @since: 0.5
        """
        self.frozen_sign.update(
            x.lower() for x in s if x.lower() not in self.should_not_sign)

    #: Load a new message to be signed or verified.
    #: @param message: an RFC822 formatted message to be signed or verified
    #: (with either \\n or \\r\\n line endings)
    #: @since: 0.5
    def set_message(self, message):
        self.headers, self.body = [], b''
        if message:
            self.headers, self.body = rfc822_parse(message)

        #: The DKIM signing domain last signed or verified.
        self.domain = None
        #: The DKIM key selector last signed or verified.
        self.selector = 'default'
        #: Signature parameters of last sign or verify.  To parse
        #: a DKIM-Signature header field that you have in hand,
        #: use L{dkim.util.parse_tag_value}.
        self.signature_fields = {}
        #: The list of headers last signed or verified.  Each header
        #: is a name,value tuple.  FIXME: The headers are canonicalized.
        #: This could be more useful as original headers.
        self.signed_headers = []
        #: The public key size last verified.
        self.keysize = 0

    def default_sign_headers(self):
        """
        Return the default list of headers to sign: those in should_sign or
        frozen_sign, with those in frozen_sign signed an extra time to prevent
        additions.
        @since: 0.5
        """
        hset = self.should_sign | self.frozen_sign
        include_headers = [x for x, y in self.headers if x.lower() in hset]
        return include_headers + [
            key for key in include_headers if key.lower() in self.frozen_sign]

    def all_sign_headers(self):
        """
        Return header list of all existing headers not in should_not_sign.
        @since: 0.5
        """
        return [
            x for x, y in self.headers if x.lower()
            not in self.should_not_sign]

    #: Sign an RFC822 message and return the DKIM-Signature header line.
    #:
    #: The include_headers option gives full control over which header fields
    #: are signed.  Note that signing a header field that doesn't exist
    #: prevents that field from being added without breaking the signature.
    #: Repeatedfields (such as Received) can be signed multiple times.
    #: Instances of the field are signed from bottom to top.  Signing a header
    #: field more times than are currently present prevents additional
    #: instances from being added without breaking the signature.
    #:
    #: The length option allows the message body to be appended to by MTAs
    #: enroute (e.g. mailing lists that append unsubscribe information)
    #: without breaking the signature.
    #:
    #: The default include_headers for this method differs from the backward
    #: compatible sign function, which signs all headers not
    #: in should_not_sign.  The default list for this method can be modified
    #: by tweaking should_sign and frozen_sign (or even should_not_sign).
    #: It is only necessary to pass an include_headers list when precise
    #: control is needed.
    #:
    #: @param selector: the DKIM selector value for the signature
    #: @param domain: the DKIM domain value for the signature
    #: @param private_key: a PKCS#1 private key in base64-encoded text form
    #: @param identity: the DKIM identity value for the signature
    #: (default "@"+domain)
    #: @param canonicalize: the canonicalization algorithms to use
    #: (default (Simple, Simple))
    #: @param include_headers: a list of strings indicating which headers
    #: are to be signed (default rfc4871 recommended headers)
    #: @param length: true if the l= tag should be included to indicate
    #: body length signed (default False).
    #: @return: DKIM-Signature header field terminated by '\r\n'
    #: @raise DKIMException: when the message, include_headers,
    #: or key are badly formed.
    def sign(
            self, selector, domain, private_key, identity=None,
            canonicalize=('relaxed', 'simple'),
            include_headers=None, length=False):
        try:
            private_key = parse_pem_private_key(private_key)
        except UnparsableKeyError as err:
            raise KeyFormatError(err)

        if identity is not None and not identity.endswith(domain):
            raise ParameterError("identity must end with domain")

        canon_policy = CanonicalizationPolicy.from_c_value(
            '/'.join(canonicalize))
        headers = canon_policy.canonicalize_headers(self.headers)

        if include_headers is None:
            include_headers = self.default_sign_headers()

        # rfc4871 says FROM is required
        if b'from' not in (x.lower() for x in include_headers):
            raise ParameterError("The From header field MUST be signed")

        # Raise exception for any SHOULD_NOT headers, call can modify
        # SHOULD_NOT if really needed.
        for header in include_headers:
            if header.lower() in self.should_not_sign:
                raise ParameterError(
                    "The {} header field SHOULD NOT be signed".format(header))

        body = canon_policy.canonicalize_body(self.body)
        hasher = HASH_ALGORITHMS[self.signature_algorithm]
        h = hasher()
        h.update(body)
        bodyhash = base64.b64encode(h.digest())

        signature_fields = [x for x in [
            (b'v', b'1'),
            (b'a', self.signature_algorithm.encode('ascii')),
            (b'c', canon_policy.to_c_value()),
            (b'd', domain),
            (b'i', identity or b'@' + domain),
            length and (b'l', str(len(body)).encode('ascii')),
            (b'q', b'dns/txt'),
            (b's', selector),
            (b't', str(int(time.time())).encode('ascii')),
            (b'h', b':'.join(include_headers)),
            (b'bh', bodyhash),
            # Force b= to fold onto it's own line so that refolding after
            # adding sig doesn't change whitespace for previous tags.
            (b'b', b''), ] if x]
        include_headers = [x.lower() for x in include_headers]
        # record what verify should extract
        self.include_headers = tuple(include_headers)

        signature_value = b'; '.join(b'='.join(x) for x in signature_fields)
        dkim_header = (b'DKIM-Signature', b' ' + signature_value)
        h = hasher()
        signature = dict(signature_fields)
        self.signed_headers = hash_headers(
            h, canon_policy, headers, include_headers, dkim_header)
        self.logger.debug("Signature headers: %r" % self.signed_headers)

        try:
            sig2 = RSASSA_PKCS1_v1_5_sign(h, private_key)
        except DigestTooLargeError:
            raise ParameterError("Digest too large for modulus")
        # Folding b= is explicity allowed, but yahoo and live.com are broken
        # signature_value += base64.b64encode(bytes(sig2))
        # Instead of leaving unfolded (which lets an MTA fold it later and
        # still breaks yahoo and live.com), we change the default signing
        # mode to relaxed/simple (for broken receivers), and fold now.
        signature_value = signature_value + base64.b64encode(bytes(sig2))

        self.domain = domain
        self.selector = selector
        self.signature_fields = signature
        return b'DKIM-Signature: ' + signature_value

    #: Verify a DKIM signature.
    #: @type idx: int
    #: @param idx: which signature to verify.
    #:               The first (topmost) signature is 0.
    #: @type dnsfunc: callable
    #: @param dnsfunc: an option function to lookup TXT resource records
    #: for a DNS domain.  The default uses dnspython or pydns.
    #: @return: True if signature verifies or False otherwise
    #: @raise DKIMException: when the message,
    #:                       signature, or key are badly formed
    def verify(self, idx=0, dnsfunc=get_txt):
        signature_headers = [
            (key, value) for key, value in self.headers
            if key.lower() == b'dkim-signature']
        if len(signature_headers) <= idx:
            return False

        # By default, we validate the first DKIM-Signature line found.
        try:
            signature = parse_tag_value(signature_headers[idx][1])
            self.signature_fields = signature
        except InvalidTagValueList as err:
            raise MessageFormatError(err)

        self.logger.debug("Signature: %r" % signature)
        validate_signature_fields(signature)
        self.domain = signature[b'd']
        self.selector = signature[b's']

        try:
            canon_policy = CanonicalizationPolicy.from_c_value(
                signature.get(b'c').decode('ascii'))
        except InvalidCanonicalizationPolicyError as err:
            raise MessageFormatError("Invalid c= value: %s" % err.args[0])

        headers = canon_policy.canonicalize_headers(self.headers)
        body = canon_policy.canonicalize_body(self.body)

        try:
            hasher = HASH_ALGORITHMS[signature[b'a'].decode('ascii')]
        except KeyError as err:
            raise MessageFormatError(
                "Unknown signature algorithm: {}".format(err.args[0]))

        if b'l' in signature:
            body = body[:int(signature[b'l'])]

        h = hasher()
        h.update(body)
        bodyhash = h.digest()
        self.logger.debug("bh: {}".format(base64.b64encode(bodyhash)))
        try:
            bh_value = base64.b64decode(re.sub(rb"\s+", "", signature[b'bh']))
        except TypeError as err:
            raise MessageFormatError(err)
        if bodyhash != bh_value:
            raise ValidationError(
                "Body hash mismatch (got {}, expected {})".format(
                    base64.b64encode(bodyhash), signature[b'bh']))
        name = "{}._domainkey.{}.".format(
            signature[b's'].decode('ascii'), signature[b'd'].decode('ascii'))

        s = dnsfunc(name)
        if not s:
            raise KeyFormatError("Missing public key: {}".format(name))
        try:
            if type(s) is str:
                s = s.encode('ascii')
            pub = parse_tag_value(s)
        except InvalidTagValueList as e:
            raise KeyFormatError(e)

        try:
            public_key = parse_public_key(base64.b64decode(pub[b'p']))
            self.keysize = get_bit_size(public_key['modulus'])
        except KeyError:
            raise KeyFormatError("Incomplete public key: {}".format(s))
        except (TypeError, UnparsableKeyError) as err:
            raise KeyFormatError(
                "Could not parse public key ({}): {}".format(pub[b'p'], err))
        include_headers = [
            x.lower() for x in re.split(br'\s*:\s*', signature[b'h'])]
        # TODO:  self.include_headers = tuple(include_headers)
        # address bug#644046 by including any additional From header
        # fields when verifying.  Since there should be only one From header,
        # this shouldn't break any legitimate messages.  This could be
        # generalized to check for extras of other singleton headers.
        if b'from' in include_headers:
            include_headers.append(b'from')
        h = hasher()
        hash_headers(
            h, canon_policy, headers, include_headers,
            signature_headers[idx])
        try:
            signature = base64.b64decode(re.sub(br'\s+', b'', signature[b'b']))
            res = RSASSA_PKCS1_v1_5_verify(h, signature, public_key)
            if res and self.keysize < self.minkey:
                raise KeyFormatError("Public key too small: {}".format(
                    self.keysize))
            return res
        except (TypeError, DigestTooLargeError) as err:
            raise KeyFormatError(
                "Digest too large for modulus: {}".format(err))


def sign(
        message, selector, domain, privkey, identity=None,
        canonicalize=('relaxed', 'simple'),
        signature_algorithm='rsa-sha256',
        include_headers=None, length=False, logger=None):
    """
    Sign an RFC822 message and return the DKIM-Signature header line.

    @param message: an RFC822 formatted message
                    (with either \\n or \\r\\n line endings)
    @param selector: the DKIM selector value for the signature
    @param domain: the DKIM domain value for the signature
    @param privkey: a PKCS#1 private key in base64-encoded text form
    @param identity: the DKIM identity value for
                     the signature (default "@"+domain)
    @param canonicalize: the canonicalization algorithms
                         to use (default (Simple, Simple))
    @param include_headers: a list of strings indicating which headers are to
                            be signed (default all headers not listed as
                            SHOULD NOT sign)
    @param length: true if the l= tag should be included to indicate body
                   length (default False)
    @param logger: a logger to which debug info will be written (default None)
    @return: DKIM-Signature header field terminated by \\r\\n
    @raise DKIMException: when the message, include_headers,
                          or key are badly formed.
    """

    d = DKIM(message, logger=logger)
    if not include_headers:
        include_headers = d.default_sign_headers()
    return d.sign(
        selector, domain, privkey,
        identity=identity, canonicalize=canonicalize,
        include_headers=include_headers, length=length)


def verify(message, logger=None, dnsfunc=get_txt, minkey=1024):
    """
    Verify the first (topmost) DKIM signature on an RFC822 formatted message.

    @param message: an RFC822 formatted message
                    (with either \\n or \\r\\n line endings)
    @param logger: a logger to which debug info will be written (default None)
    @return: True if signature verifies or False otherwise
    """
    d = DKIM(message, logger=logger, minkey=minkey)
    try:
        return d.verify(dnsfunc=dnsfunc)
    except DKIMException as err:
        if logger is not None:
            logger.error(str(err))
        print(err)
        return False
