#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-10
import re


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

