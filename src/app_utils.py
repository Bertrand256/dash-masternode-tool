#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-10
import re
import base64
import binascii
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def extract_app_version(lines):
    """
    Extracts version string from array of lines (content of version.txt file)
    :param lines:
    :return: version string
    """
    for line in lines:
        parts = [elem.strip() for elem in line.split('=')]
        if len(parts) == 2 and parts[0].lower() == 'version_str':
            return parts[1].strip("'")
    return ''


def version_str_to_number(version_str):
    elems = version_str.split('.')
    if elems:
        # last element of a version string can have a suffix
        last_elem = elems[len(elems) - 1]
        if not last_elem.isdigit():
            res = re.findall(r'^\d+', last_elem)
            if res:
                elems[len(elems) - 1] = res[0]
            else:
                del elems[len(elems) - 1]

    ver_list = [n.zfill(4) for n in elems]
    version_nr_str = ''.join(ver_list)
    version_nr = int(version_nr_str)
    return version_nr


def encrypt(input_str, key):
    salt = b'D9\x82\xbfSibW(\xb1q\xeb\xd1\x84\x118'
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(key.encode('utf-8')))
    fer = Fernet(key)
    h = fer.encrypt(input_str.encode('utf-8'))
    h = h.hex()
    return h


def decrypt(input_str, key):
    try:
        input_str = binascii.unhexlify(input_str)
        salt = b'D9\x82\xbfSibW(\xb1q\xeb\xd1\x84\x118'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(key.encode('utf-8')))
        fer = Fernet(key)
        h = fer.decrypt(input_str)
        h = h.decode('utf-8')
    except:
        return ''
    return h


def seconds_to_human(number_of_seconds, out_seconds=True, out_minutes=True, out_hours=True):
    """
    Converts number of seconds to string representation.
    :param out_seconds: False, if seconds part in output is to be trucated
    :param number_of_seconds: number of seconds.
    :return: string representation of time delta
    """
    human_strings = []

    weeks = 0
    days = 0
    hours = 0
    if number_of_seconds > 604800:
        # weeks
        weeks = int(number_of_seconds / 604800)
        number_of_seconds = number_of_seconds - (weeks * 604800)
        elem_str = str(int(weeks)) + ' week'
        if weeks > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if number_of_seconds > 86400:
        # days
        days = int(number_of_seconds / 86400)
        number_of_seconds = number_of_seconds - (days * 86400)
        elem_str = str(int(days)) + ' day'
        if days > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if out_hours and number_of_seconds > 3600:
        hours = int(number_of_seconds / 3600)
        number_of_seconds = number_of_seconds - (hours * 3600)
        elem_str = str(int(hours)) + ' hour'
        if hours > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if out_minutes and number_of_seconds > 60:
        minutes = int(number_of_seconds / 60)
        number_of_seconds = number_of_seconds - (minutes * 60)
        elem_str = str(int(minutes)) + ' minute'
        if minutes > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if out_seconds and number_of_seconds >= 1:
        elem_str = str(int(number_of_seconds)) + ' second'
        if number_of_seconds > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    return ' '.join(human_strings)
