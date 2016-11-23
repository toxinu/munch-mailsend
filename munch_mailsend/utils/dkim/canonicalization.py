# This software is provided 'as-is', without any express or implied
# warranty.  In no event will the author be held liable for any damages
# arising from the use of this software.
#
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
#
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software. If you use this software
#    in a product, an acknowledgment in the product documentation would be
#    appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not be
#    misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source distribution.
#
# Copyright (c) 2008 Greg Hewgill http://hewgill.com
#
# This has been modified from the original software.
# Copyright (c) 2011 William Grant <me@williamgrant.id.au>

import re

from .exceptions import InvalidCanonicalizationPolicyError


__all__ = [
    'CanonicalizationPolicy',
    'InvalidCanonicalizationPolicyError',
    ]


def strip_trailing_whitespace(content):
    return re.sub(br"[\t ]+\r\n", b"\r\n", content)


def compress_whitespace(content):
    return re.sub(br"[\t ]+", b" ", content)


def strip_trailing_lines(content):
    return re.sub(br"(\r\n)*$", b"\r\n", content)


def unfold_header_value(content):
    return re.sub(br"\r\n", b"", content)


class Simple:
    """Class that represents the "simple" canonicalization algorithm."""

    name = "simple"

    @staticmethod
    def canonicalize_headers(headers):
        # No changes to headers.
        return headers

    @staticmethod
    def canonicalize_body(body):
        # Ignore all empty lines at the end of the message body.
        return strip_trailing_lines(body)


class Relaxed:
    """Class that represents the "relaxed" canonicalization algorithm."""

    name = "relaxed"

    @staticmethod
    def canonicalize_headers(headers):
        # Convert all header field names to lowercase.
        # Unfold all header lines.
        # Compress WSP to single space.
        # Remove all WSP at the start or end of the field value (strip).
        canonicalized_headers = []
        for header, value in headers:
            canonicalized_headers.append((
                header.lower().rstrip(),
                compress_whitespace(
                    unfold_header_value(value)).strip() + b'\r\n'))
        return canonicalized_headers

    @staticmethod
    def canonicalize_body(body):
        # Remove all trailing WSP at end of lines.
        # Compress non-line-ending WSP to single space.
        # Ignore all empty lines at the end of the message body.
        return strip_trailing_lines(
            compress_whitespace(strip_trailing_whitespace(body)))


class CanonicalizationPolicy:
    def __init__(self, header_algorithm, body_algorithm):
        self.header_algorithm = header_algorithm
        self.body_algorithm = body_algorithm

    @classmethod
    def from_c_value(cls, canonicalization):
        """Construct the canonicalization policy described by a c= value.

        May raise an C{InvalidCanonicalizationPolicyError} if the given
        value is invalid

        @param c: c= value from a DKIM-Signature header field
        @return: a C{CanonicalizationPolicy}
        """
        if canonicalization is None:
            canonicalization = 'simple/simple'

        splitted_canonicalization = canonicalization.split('/')
        if len(splitted_canonicalization) not in (1, 2):
            raise InvalidCanonicalizationPolicyError(canonicalization)
        if len(splitted_canonicalization) == 1:
            splitted_canonicalization.append('simple')
        headers_canonicalization = splitted_canonicalization[0]
        body_canonicalization = splitted_canonicalization[1]
        try:
            header_algorithm = ALGORITHMS[headers_canonicalization]
            body_algorithm = ALGORITHMS[body_canonicalization]
        except KeyError as err:
            raise InvalidCanonicalizationPolicyError(err.args[0])
        return cls(header_algorithm, body_algorithm)

    def to_c_value(self):
        return b'/'.join((
            self.header_algorithm.name.encode('ascii'),
            self.body_algorithm.name.encode('ascii')))

    def canonicalize_headers(self, headers):
        return self.header_algorithm.canonicalize_headers(headers)

    def canonicalize_body(self, body):
        return self.body_algorithm.canonicalize_body(body)


ALGORITHMS = dict((c.name, c) for c in (Simple, Relaxed))
