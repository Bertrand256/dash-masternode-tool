FROM ubuntu:17.10
MAINTAINER \
[Bertrand256 <bertrand256gh@protonmail.com>]
RUN apt-get update \
 && apt-get -y upgrade \
 && apt-get -y install libudev-dev libusb-1.0-0-dev libfox-1.6-dev autotools-dev autoconf automake libtool libpython3-all-dev python3-pip git \
 && pip3 install virtualenv \
 && cd ~ \
 && mkdir dmt \
 && cd dmt \
 && virtualenv -p python3 venv \
 && . venv/bin/activate \
 && pip install --upgrade setuptools \
 && git clone https://github.com/Bertrand256/dash-masternode-tool \
 && cd dash-masternode-tool/ \
 && pip install -r requirements.txt \
 && cd ~/dmt \
 && echo "#!/bin/sh" | tee build-dmt.sh \
 && echo "cd ~/dmt" | tee -a build-dmt.sh \
 && echo ". venv/bin/activate" | tee -a build-dmt.sh \
 && echo "cd dash-masternode-tool" | tee -a build-dmt.sh \
 && echo "git fetch --all" | tee -a build-dmt.sh \
 && echo "git reset --hard origin/master" | tee -a build-dmt.sh \
 && echo "pip install -r requirements.txt" | tee -a build-dmt.sh \
 && echo "pyinstaller --distpath=../dist/linux --workpath=../dist/linux/build dash_masternode_tool.spec" | tee -a build-dmt.sh \
 && echo "cd .." | tee -a build-dmt.sh \
 && chmod +x build-dmt.sh

CMD ~/dmt/build-dmt.sh
