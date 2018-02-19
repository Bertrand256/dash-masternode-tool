## Building DashMasternodeTool executable on Fedora Linux

### Method based on physical or virtual linux machine

From your linux terminal execute the following commands:

```
[dmt@fedora /]# sudo yum update -y
[dmt@fedora /]# sudo yum group install -y "Development Tools" "Development Libraries"
[dmt@fedora /]# sudo yum install -y redhat-rpm-config python3-devel libusbx-devel libudev-devel
[dmt@fedora /]# sudo pip3 install virtualenv
[dmt@fedora /]# cd ~
[dmt@fedora /]# mkdir dmt && cd dmt
[dmt@fedora /]# virtualenv -p python3 venv
[dmt@fedora /]# . venv/bin/activate
[dmt@fedora /]# pip install --upgrade setuptools
[dmt@fedora /]# git clone https://github.com/Bertrand256/dash-masternode-tool
[dmt@fedora /]# cd dash-masternode-tool/
[dmt@fedora /]# pip install -r requirements.txt
[dmt@fedora /]# pyinstaller --distpath=../dist/linux --workpath=../dist/linux/build dash_masternode_tool.spec
```

As a  result of running of these commands, you should get the following files:
* `~/dmt/dist/linux/DashMasternodeTool`: executable file
* `~/dmt/dist/all/DashMasternodeTool_<verion_string>.linux.tar.gz`: compressed executable


### Method based on Docker

This method is based on using a dedicated **docker image**, configured to perform an automatic build process of the *DashMasternodeTool* application. 

The advantage of this method is its simplicity and the fact that it does not make any changes in the list of installed apps/libraries on your physical/virtual machine - all necessary dependencies are installed in the so-called Docker container.

The second important advantage is that this compilation can be also carried out on Windows or Mac OS (if you have Docker installed on them), but keep in mind that the result of the compilation will be a Linux executable anyway.

> **Note: If you are not performing this procedure for the first time (for example you are building a newer version of DMT), skip the steps 3 and 4.**

#### 1. Create an empty directory
In the following part of the document we will refer to it as the *working directory*.

#### 2. Open terminal app and `cd` to the *working directory*

```
cd <working_directory>
```

#### 3. Install the *bertrand256/build-dmt* Docker image

Skip this step if you have done this before. At any time, you can check whether the required image exists in your local machine by issuing following command:

```
docker images bertrand256/build-dmt
```

The required image can be obtained with one of two possible ways:

**Download it from Docker Hub**

Execute the following command:

```
docker pull bertrand256/build-dmt
```

, or:

**Build the image yourself, using the Dockerfile file from the DMT project repository.** 

* Download the https://github.com/Bertrand256/dash-masternode-tool/blob/master/build/fedora/Dockerfile file and place it inside the *working directory*
* Execute the following command:
```
docker build -t bertrand256/build-dmt .
```

#### 4. Create a Docker container

Docker container is an instance of an image (as in the software development world, object is an instance of a class) and it exists until you delete it. Thus, if you have created the containter before, skip this step. In this procedure, to easily identify the container, we give it a specific name (dmtbuild) during its creation, so, you can easily check if it exists in your system.

```
docker ps -a --filter name=dmtbuild --filter ancestor=bertrand256/build-dmt
```
Create the container:

``` 
docker create --name dmtbuild -it bertrand256/build-dmt
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