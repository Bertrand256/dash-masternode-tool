## Building the DMT executable file on Ubuntu Linux

### Method based on physical or virtual linux machine

An Ubuntu distribution with Python 3.8 is required to build DMT. This example uses Ubuntu 16.04, which comes with an 
appropriate version installed by default. You can verify the Python version by typing:

```
python3 --version
```

You should see a response similar to the following:

  `Python 3.8.x`

After making sure that you have the correct Python version, execute the following commands from the terminal:

```
sudo apt update \
&& sudo apt -y upgrade \
&& sudo apt -y install software-properties-common \
&& sudo add-apt-repository -y ppa:deadsnakes/ppa \
&& sudo apt update \
&& sudo apt -y install curl libxcb-xinerama0 libudev-dev libusb-1.0-0-dev libfox-1.6-dev autotools-dev autoconf automake libtool libpython3-all-dev python3.8 python3.8-venv python3.8-dev git cmake python3.8-distutils \
&& cd ~ \
&& curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py \
&& sudo python3.8 get-pip.py \
&& mkdir -p dmt-build \
&& cd dmt-build \
&& python3.8 -m pip install virtualenv \
&& python3.8 -m virtualenv -p python3.8 venv \
&& . venv/bin/activate \
&& git clone https://github.com/Bertrand256/dash-masternode-tool \
&& cd dash-masternode-tool/ \
&& pip install -r requirements.txt \
&& mkdir -p ~/dmt-build/dist
pyinstaller --distpath=dist/linux --workpath=dist/linux/build dash_masternode_tool.spec
```

The following files will be created once the build has completed successfully:

* Executable: `~/dmt-build/dist/linux/DashMasternodeTool`
* Compressed executable: `~/dmt-build/dist/all/DashMasternodeTool_<verion_string>.linux.tar.gz`


### Method based on Docker

This method uses a dedicated **docker image** configured to carry out an automated build process for *Dash Masternode Tool*. The advantage of this method is its simplicity, and the fact that it does not make any changes in the list of installed apps/libraries on your physical/virtual machine. All necessary dependencies are installed inside the Docker container. The second important advantage is that compilation can also be carried out on Windows or macOS (if Docker is installed), but keep in mind that the result of the build will be a Linux executable.

> **Note: skip steps 1 to 4 if you have done them before - if you are just building a newer version of DMT, go 
> straight to step 5.**

#### 1. Create a new directory
We will refer to this as the *working directory* in the remainder of this documentation.

#### 2. Open the terminal app and `cd` to the *working directory*

```
cd <working_directory>
```

#### 3. Install the *bertrand256/build-dmt:ubuntu* Docker image

Skip this step if you have done this before. At any time, you can check whether the required image exists in your local machine by issuing following command:

```
docker images bertrand256/build-dmt:ubuntu
```

The required image can be obtained in one of two ways:

**Download from Docker Hub**

Execute the following command:

```
docker pull bertrand256/build-dmt:ubuntu
```

**Build the image yourself, using the Dockerfile file from the DMT project repository.** 

* Download the https://github.com/Bertrand256/dash-masternode-tool/blob/master/build/ubuntu/Dockerfile file and place it in the *working directory*
* Execute the following command:
```
docker build -t bertrand256/build-dmt:ubuntu .
```

#### 4. Create a Docker container

A Docker container is an instance of an image (similar to how an object is an instance of a class in the software development world), and it exists until you delete it. You can therefore skip this step if you have created the container before. To easily identify the container, we give it a specific name (dmtbuild) when it is created, so you can easily check if it exists in your system.

```
docker ps -a --filter name=dmtbuild --filter ancestor=bertrand256/build-dmt:ubuntu
```
Create the container:

``` 
mkdir -p build
docker create --name dmtbuild -v $(pwd)/build:/root/dmt-build/dist -it bertrand256/build-dmt:ubuntu
```

#### 5. Build the Dash Masternode Tool executable

```
docker start -ai dmtbuild
```

After the process completes, the resulting files can be found in the `build` subdirectory of your current directory:
* Executable: `linux/DashMasternodeTool`
* Compressed executable: `all/DashMasternodeTool_<verion_string>.linux.tar.gz`
