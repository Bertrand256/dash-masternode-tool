FROM ubuntu:16.04
MAINTAINER \
[Bertrand256 <blogin@protonmail.com>]
RUN apt update \
 && apt -y upgrade \
 && apt -y install software-properties-common \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt update \
 && apt -y install curl libxcb-xinerama0 libudev-dev libusb-1.0-0-dev libfox-1.6-dev autotools-dev autoconf automake libtool libpython3-all-dev python3.8 python3.8-venv python3.8-dev git cmake python3.8-distutils \
 && cd ~ \
 && curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py \
 && python3.8 get-pip.py \
 && mkdir -p dmt-build \
 && cd dmt-build \
 && python3.8 -m pip install virtualenv \
 && python3.8 -m virtualenv -p python3.8 venv \
 && . venv/bin/activate \
 && git clone https://github.com/Bertrand256/dash-masternode-tool \
 && cd dash-masternode-tool/ \
 && pip install -r requirements.txt \
 && cd ~ \
 && echo "#!/bin/sh" | tee build-dmt.sh \
 && echo "cd ~/dmt-build/" | tee -a build-dmt.sh \
 && echo ". venv/bin/activate" | tee -a build-dmt.sh \
 && echo "cd dash-masternode-tool" | tee -a build-dmt.sh \
 && echo "git fetch --all" | tee -a build-dmt.sh \
 && echo "git reset --hard origin/master" | tee -a build-dmt.sh \
 && echo "pip install -r requirements.txt" | tee -a build-dmt.sh \
 && echo "pyinstaller --distpath=~/dmt-build/dist/linux --workpath=~/dmt-build/dist/linux/build dash_masternode_tool.spec" | tee -a build-dmt.sh \
 && echo "cd .." | tee -a build-dmt.sh \
 && chmod +x build-dmt.sh

CMD ~/build-dmt.sh
