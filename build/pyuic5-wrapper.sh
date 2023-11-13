# Qt's pyuic5 wrapper, whose purpose is to:
#  - remove the UI file path from the generated python files to avoid changes to the UI python files when developing
#    on different machines/directories
#  - remove version of the pyuic5 being included in the generated python files to avoid changes to the source files
#    when only pyuic5 version changes (not the source file itself)

pyuic5 $1 | sed -E "s|(# Form implementation generated from reading ui file )'?(.*/)*([^']*)'?|\1\3|g" | sed -E "s|(# Created by: PyQt5 UI code generator)(.*)|\1|g" > $2
