import re
import time

from .exceptions import DuplicateTag
from .exceptions import InvalidTagSpec
from .exceptions import ValidationError
from .exceptions import MessageFormatError

# FWS  =  ([*WSP CRLF] 1*WSP) /  obs-FWS ; Folding white space  [RFC5322]
FWS = br'(?:(?:\s*\r?\n)?\s+)?'


def get_bit_size(x):
    """Return size of long in bits."""
    return len(bin(x)) - 2


def hash_headers(
        hasher, canonicalize_headers, headers, include_headers, sigheader):
    """ Update hash for signed message header fields. """
    sign_headers = select_headers(headers, include_headers)
    # The call to _remove() assumes that the signature b= only appears
    # once in the signature header
    cheaders = canonicalize_headers.canonicalize_headers(
        [(sigheader[0], sigheader[1])])
    # the dkim sig is hashed with no trailing crlf, even if the
    # canonicalization algorithm would add one.
    for x, y in sign_headers + [(x, y.rstrip()) for x, y in cheaders]:
        hasher.update(x)
        hasher.update(b':')
        hasher.update(y)
    return sign_headers


def select_headers(headers, include_headers):
    """Select message header fields to be signed/verified.

    >>> h = [('from','biz'),('foo','bar'),('from','baz'),('subject','boring')]
    >>> i = ['from','subject','to','from']
    >>> select_headers(h,i)
    [('from', 'baz'), ('subject', 'boring'), ('from', 'biz')]
    >>> h = [('From','biz'),('Foo','bar'),('Subject','Boring')]
    >>> i = ['from','subject','to','from']
    >>> select_headers(h,i)
    [('From', 'biz'), ('Subject', 'Boring')]
    """
    signature_headers = []
    last_index = {}
    for header in include_headers:
        assert header == header.lower()
        i = last_index.get(header, len(headers))
        while i > 0:
            i -= 1
            if header == headers[i][0].lower():
                signature_headers.append(headers[i])
                break
        last_index[header] = i
    return signature_headers


def validate_signature_fields(signature):
    """
    Validate DKIM-Signature fields.

    Basic checks for presence and correct formatting of mandatory fields.
    Raises a ValidationError if checks fail, otherwise returns None.

    @param sig: A dict mapping field keys to values.
    """
    mandatory_fields = (b'v', b'a', b'b', b'bh', b'd', b'h', b's')
    for field in mandatory_fields:
        if field not in signature:
            raise ValidationError("signature missing {}=".format(field))

    if signature[b'v'] != b'1':
        raise ValidationError("v= value is not 1 ({})".format(signature[b'v']))
    if re.match(br"[\s0-9A-Za-z+/]+=*$", signature[b'b']) is None:
        raise ValidationError(
            "b= value is not valid base64 ({})".format(signature[b'b']))
    if re.match(br"[\s0-9A-Za-z+/]+=*$", signature[b'bh']) is None:
        raise ValidationError(
            "bh= value is not valid base64 (%{})".format(signature[b'bh']))
    # Nasty hack to support both str and bytes... check for both the
    # character and integer values.
    if b'i' in signature and (
            not signature[b'i'].lower().endswith(signature[b'd'].lower()) or
            signature[b'i'][-len(
                signature[b'd'])-1] not in ('@', '.', 64, 46)):
        raise ValidationError(
            "i= domain is not a subdomain of d= (i={} d={})".format(
                signature[b'i'], signature[b'd']))
    if b'l' in signature and re.match(br"\d{,76}$", signature[b'l']) is None:
        raise ValidationError(
            "l= value is not a decimal integer ({})".format(signature[b'l']))
    if b'q' in signature and signature[b'q'] != b'dns/txt':
        raise ValidationError("q= value is not dns/txt ({})".format(
            signature[b'q']))
    now = int(time.time())
    slop = 36000		# 10H leeway for mailers with inaccurate clocks
    t_sign = 0
    if b't' in signature:
        if re.match(br"\d+$", signature[b't']) is None:
            raise ValidationError(
                "t= value is not a decimal integer ({})".format(
                    signature[b't']))
        t_sign = int(signature[b't'])
        if t_sign > now + slop:
            raise ValidationError("t= value is in the future ({})".format(
                signature[b't']))
    if b'x' in signature:
        if re.match(rb"\d+$", signature[b'x']) is None:
            raise ValidationError(
                "x= value is not a decimal integer ({})".format(
                    signature[b'x']))
        x_sign = int(signature[b'x'])
        if x_sign < now - slop:
            raise ValidationError(
                "x= value is past ({})".format(signature[b'x']))
        if x_sign < t_sign:
            raise ValidationError(
                "x= value is less than t= value (x={} t={})".format(
                    signature[b'x'], signature[b't']))


def rfc822_parse(message):
    """
    Parse a message in RFC822 format.

    @param message: The message in RFC822 format.
                    Either CRLF or LF is an accepted line separator.
    @return: Returns a tuple of (headers, body)
             where headers is a list of (name, value) pairs.
    The body is a CRLF-separated string.
    """
    headers = []
    lines = re.split(br"\r?\n", message)
    i = 0
    while i < len(lines):
        if len(lines[i]) == 0:
            # End of headers, return what we have plus the body,
            # excluding the blank line.
            i += 1
            break
        if lines[i][0] in ("\x09", "\x20", 0x09, 0x20):
            headers[-1][1] += lines[i] + b"\r\n"
        else:
            m = re.match(br"([\x21-\x7e]+?):", lines[i])
            if m is not None:
                headers.append([m.group(1), lines[i][m.end(0):] + b"\r\n"])
            elif lines[i].startswith(b"From "):
                pass
            else:
                raise MessageFormatError(
                    "Unexpected characters in RFC822 header: {}".format(
                        lines[i]))
        i += 1
    return (headers, b"\r\n".join(lines[i:]))


def parse_tag_value(tag_list):
    """
    Parse a DKIM Tag=Value list.

    Interprets the syntax specified by RFC4871 section 3.2.
    Assumes that folding whitespace is already unfolded.

    @param tag_list: A bytes string containing a DKIM Tag=Value list.
    """
    tags = {}
    tag_specs = tag_list.strip().split(b';')
    # Trailing semicolons are valid.
    if not tag_specs[-1]:
        tag_specs.pop()
    for tag_spec in tag_specs:
        try:
            key, value = tag_spec.split(b'=', 1)
        except ValueError:
            raise InvalidTagSpec(tag_spec)
        if key.strip() in tags:
            raise DuplicateTag(key.strip())
        tags[key.strip()] = value.strip()
    return tags
