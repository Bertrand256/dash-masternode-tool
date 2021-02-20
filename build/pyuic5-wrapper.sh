# Qt's pyuic5 wrapper to remove the UI file path from the generated python files and thus to avoid
# constant changes to the UI python files when developing on different machines.

pyuic5 $1 | sed -E "s|(# Form implementation generated from reading ui file )'(.*)/(.*)'|\1\3|g" > $2
