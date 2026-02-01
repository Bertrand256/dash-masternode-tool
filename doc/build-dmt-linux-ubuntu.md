## Building the DMT executable file on Ubuntu Linux

### Method based on physical or virtual linux machine

An Ubuntu distribution with Python 3.11 is required to build DMT. This example uses Ubuntu 20.04 and `uv` to manage Python versions and environments. You can verify if `uv` is installed by typing:

```
uv --version
```

After making sure that you have `uv` installed (or after installing it in the steps below), execute the following commands from the terminal:

```
sudo apt update \
&& sudo apt -y upgrade \
&& sudo DEBIAN_FRONTEND=noninteractive apt -y install curl libxcb-xinerama0 libudev-dev libusb-1.0-0-dev libfox-1.6-dev autotools-dev autoconf automake libtool git cmake \
   libspeechd2 libwayland-cursor0 libxkbcommon0 libxcb-xkb1 libxkbcommon-x11-0 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-icccm4 libxcb-render0 libxcomposite1 libwayland-egl1 \
&& curl -LsSf https://astral.sh/uv/install.sh | sh \
&& source $HOME/.local/bin/env \
&& mkdir -p ~/dmt-build \
&& cd ~/dmt-build \
&& uv venv --python 3.11 venv \
&& . venv/bin/activate \
&& git clone https://github.com/Bertrand256/dash-masternode-tool \
&& cd dash-masternode-tool/ \
&& uv pip install -r requirements.txt \
&& mkdir -p ~/dmt-build/dist \
&& pyinstaller --distpath=../dist/linux --workpath=../dist/linux/build dash_masternode_tool.spec \
&& . build/ubuntu/build-appimage.sh
```

The following files will be created once the build has completed successfully:

* Executable: `~/dmt-build/dist/linux/DashMasternodeTool`
* Compressed executable: `~/dmt-build/dist/all/DashMasternodeTool_<version_string>.linux.tar.gz`
* AppImage: `~/dmt-build/dist/all/DashMasternodeTool_<version_string>.AppImage`


### Method based on Docker

This method uses a dedicated **Docker image** configured to carry out an automated build process for *Dash Masternode Tool*. The advantage of this method is its simplicity, and the fact that it does not make any changes in the list of installed apps/libraries on your physical/virtual machine. All necessary dependencies are installed inside the Docker container. 

The build process is performed inside an Ubuntu 20.04 container, which ensures that the resulting binaries are compatible with older Linux distributions.

#### 1. Clone the DMT repository

If you haven't already, clone the Dash Masternode Tool repository to your local machine:

```
git clone https://github.com/Bertrand256/dash-masternode-tool
cd dash-masternode-tool
```

#### 2. Build the Docker image

Build the Docker image using the provided `Dockerfile` located in the `build/ubuntu` directory:

```
docker build -t dmt-build-ubuntu build/ubuntu
```

#### 3. Run the build process

Run the build container. We map the current directory to `/root/dmt` inside the container so that the source code is accessible and the resulting binaries are saved back to your host machine:

```
docker run --rm -v $(pwd):/root/dmt dmt-build-ubuntu
```

#### 4. Collect the binaries

After the process completes, the resulting files can be found in the `dist/linux` and `dist/all` subdirectories:

* Executable: `dist/linux/DashMasternodeTool`
* Compressed executable: `dist/all/DashMasternodeTool_<version_string>.linux.tar.gz`
* AppImage: `dist/all/DashMasternodeTool_<version_string>.AppImage`

### Signing the release

After building the binaries and creating a release on GitHub, you can use the `scripts/sign-release.sh` script to sign the assets and update the release description with SHA512 hashes. This script requires `github-cli (gh)` and `keybase` to be installed and configured.

```bash
./scripts/sign-release.sh
```

Follow the prompts to enter the release tag name. The script will download assets, sign them, upload the signatures, and update the release notes.
