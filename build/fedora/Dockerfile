FROM fedora
MAINTAINER \
[Bertrand256 <bertrand256gh@protonmail.com>]
RUN yum update -y \
 && yum group install -y "Development Tools" "Development Libraries" \
 && yum install -y redhat-rpm-config python3-devel libusbx-devel libudev-devel \
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
 && set +H \
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
