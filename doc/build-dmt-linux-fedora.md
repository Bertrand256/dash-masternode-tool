## Building the Dash Masternode Tool executable on Fedora Linux

### Method based on physical or virtual linux machine

Execute the following commands from the terminal:

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

The following files will be created once the build has completed successfully:
* Executable: `~/dmt/dist/linux/DashMasternodeTool`
* Compressed executable: `~/dmt/dist/all/DashMasternodeTool_<verion_string>.linux.tar.gz`


### Method based on Docker

This method uses a dedicated **docker image** configured to carry out an automated build process for *Dash Masternode Tool*. The advantage of this method is its simplicity and the fact that it does not make any changes in the list of installed apps/libraries on your physical/virtual machine. All necessary dependencies are installed inside the Docker container. The second important advantage is that compilation can also be carried out on Windows or macOS (if Docker is installed), but keep in mind that the result of the build will be a Linux executable.

> **Note: Skip steps 3 and 4 if you are not performing this procedure for the first time (building a newer version of DMT, for example)**

#### 1. Create a new directory
We will refer to this as the *working directory* in the remainder of this documentation.

#### 2. Open the terminal app and `cd` to the *working directory*

```
cd <working_directory>
```

#### 3. Install the *bertrand256/build-dmt* Docker image

Skip this step if you have done this before. At any time, you can check whether the required image exists in your local machine by issuing following command:

```
docker images bertrand256/build-dmt
```

The required image can be obtained in one of two ways:

**Download from Docker Hub**

Execute the following command:

```
docker pull bertrand256/build-dmt
```

**Build the image yourself, using the Dockerfile file from the DMT project repository.** 

* Download the https://github.com/Bertrand256/dash-masternode-tool/blob/master/build/fedora/Dockerfile file and place it in the *working directory*
* Execute the following command:
```
docker build -t bertrand256/build-dmt .
```

#### 4. Create a Docker container

A Docker container is an instance of an image (similar to how an object is an instance of a class in the software development world), and it exists until you delete it. You can therefore skip this step if you have created the container before. To easily identify the container, we give it a specific name (dmtbuild) when it is created so you can easily check if it exists in your system.

```
docker ps -a --filter name=dmtbuild --filter ancestor=bertrand256/build-dmt
```
Create the container:

``` 
docker create --name dmtbuild -it bertrand256/build-dmt
```

#### 5. Build the Dash Masternode Tool executable

```
docker start -ai dmtbuild
```

#### 6. Copy the build result to your *working directory*

```
docker cp dmtbuild:/root/dmt/dist/all dmt-executable
```

This command completes the procedure. The `dmt-executable` directory inside your *working directory* will contain a compressed Dash Masternode Tool executable.
