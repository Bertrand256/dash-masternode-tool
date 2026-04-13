FROM ubuntu:20.04
MAINTAINER \
[Bertrand256 <blogin@protonmail.com>]
ARG DEBIAN_FRONTEND=noninteractive
RUN apt update \
 && apt -y upgrade \
 && apt -y install curl libxcb-xinerama0 libudev-dev libusb-1.0-0-dev libfox-1.6-dev autotools-dev autoconf automake libtool libpython3-all-dev git cmake execstack \
    libspeechd2 libwayland-cursor0 libxkbcommon0 libxcb-xkb1 libxkbcommon-x11-0 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-icccm4 libxcb-render0 libxcomposite1 libwayland-egl1 \
    wget file libfuse2 \
 && curl -LsSf https://astral.sh/uv/install.sh | sh \
 && export PATH="/root/.local/bin:$PATH" \
 && wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage -O /usr/local/bin/appimagetool \
 && chmod +x /usr/local/bin/appimagetool

WORKDIR /root/dmt

CMD export PATH="/root/.local/bin:$PATH" \
 && uv venv --python 3.11 \
 && . .venv/bin/activate \
 && uv pip install -r requirements.txt \
 && pyinstaller --distpath=./dist/linux --workpath=./build/linux dash_masternode_tool.spec \
 && ( [ -f ./dist/linux/DashMasternodeTool ] && execstack -c ./dist/linux/DashMasternodeTool || true ) \
 && ( [ -d ./dist/linux/_internal ] && find ./dist/linux/_internal -name "libpython*.so*" -exec execstack -c {} + || true ) \
 && . build/ubuntu/build-appimage.sh
