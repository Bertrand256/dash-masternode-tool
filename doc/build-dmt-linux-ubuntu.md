## Building DashMasternodeTool executable on Ubuntu Linux

### Method based on physical or virtual linux machine

To follow the procedure you need to choose the Ubuntu distribution, for which you will be able to install Python version 3.6 (or greater), for example Ubuntu 17.10, which has it istalled by default.

After making sure that you have the correct Python version, execute the following commands from your linux terminal:

```
[dmt@ubuntu /]# sudo apt-get update
[dmt@ubuntu /]# sudo apt-get -y upgrade
[dmt@ubuntu /]# sudo apt-get -y install libudev-dev libusb-1.0-0-dev libfox-1.6-dev autotools-dev autoconf automake libtool libpython3-all-dev python3-pip git
[dmt@ubuntu /]# sudo pip3 install virtualenv
[dmt@ubuntu /]# cd ~
[dmt@ubuntu /]# mkdir dmt && cd dmt
[dmt@ubuntu /]# virtualenv -p python3 venv
[dmt@ubuntu /]# . venv/bin/activate
[dmt@ubuntu /]# pip install --upgrade setuptools
[dmt@ubuntu /]# git clone https://github.com/Bertrand256/dash-masternode-tool
[dmt@ubuntu /]# cd dash-masternode-tool/
[dmt@ubuntu /]# pip install -r requirements.txt
[dmt@ubuntu /]# pyinstaller --distpath=../dist/linux --workpath=../dist/linux/build dash_masternode_tool.spec
```

As a  result of running of these commands, you should get the following files:
* `~/dmt/dist/linux/DashMasternodeTool`: executable file
* `~/dmt/dist/all/DashMasternodeTool_<verion_string>.linux.tar.gz`: compressed executable


### Method based on Docker

This method is based on using a dedicated **docker image**, configured to carry on an automatic build process of the *DashMasternodeTool* application. 

The advantage of this method is its simplicity and the fact that it does not make any changes in the list of installed apps/libraries on your physical/virtual machine - all necessary dependencies are installed in the so-called Docker container.

The second important advantage is that this compilation can be also carried out on Windows or Mac OS (if you have Docker installed on them), but keep in mind that the result of the compilation will be a Linux executable anyway.

> **Note: If you are not performing this procedure for the first time (for example you are building a newer version of DMT), skip the steps 3 and 4.**

#### 1. Create an empty directory
In the following part of the document we will refer to it as the *working directory*.

#### 2. Open terminal app and `cd` to the *working directory*

```
cd <working_directory>
```

#### 3. Install the *bertrand256/build-dmt:ubuntu* Docker image

Skip this step if you have done this before. At any time, you can check whether the required image exists in your local machine by issuing following command:

```
docker images bertrand256/build-dmt:ubuntu
```

The required image can be obtained with one of two possible ways:

**Download it from Docker Hub**

Execute the following command:

```
docker pull bertrand256/build-dmt:ubuntu
```

, or:

**Build the image yourself, using the Dockerfile file from the DMT project repository.** 

* Download the https://github.com/Bertrand256/dash-masternode-tool/blob/master/build/ubuntu/Dockerfile file and place it inside the *working directory*
* Execute the following command:
```
docker build -t bertrand256/build-dmt:ubuntu .
```

#### 4. Create a Docker container

Docker container is an instance of an image (as in the software development world, object is an instance of a class) and it exists until you delete it. Thus, if you have created the containter before, skip this step. In this procedure, to easily identify the container, we give it a specific name (dmtbuild) during its creation, so, you can easily check if it exists in your system.

```
docker ps -a --filter name=dmtbuild --filter ancestor=bertrand256/build-dmt:ubuntu
```
Create the container:

``` 
docker create --name dmtbuild -it bertrand256/build-dmt:ubuntu
```

#### 5. Build the DashMasternodeTool executable

```
docker start -ai dmtbuild
```

#### 6. Copy the result to your *working directory*

```
docker cp dmtbuild:/root/dmt/dist/all dmt-executable
```

This command ends the procedure. As a result you will see the `dmt-executable` directory inside your *working directory* and the compressed DashMasternodeTool executable inside of it.