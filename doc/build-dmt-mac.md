## Building the DMT executable file on macOS

You can build Dash Masternode Tool for macOS by opening the Terminal app and running the following commands:

* Install *Homebrew*:

  ```
  curl -fsSL -o install.sh https://raw.githubusercontent.com/Homebrew/install/master/install.sh
  /bin/bash install.sh
  ```

  Installation takes about 5 minutes to complete.

* Install *libusb*
  ```
  brew install libusb
  ```
  
* Install *Python 3*:

  ```
  brew install python3
  ```

* After the installation process completes, make sure that the Python version installed is 3.6 or newer. 
  DMT won't compile on older versions of Python, or even older versions of Python 3:

  ```
  python3 --version
  ```

  You should see a response similar to the following: `Python 3.8.x`, where x means the latest build number.


* Create a Python virtual environment for DMT:

  ```
  mkdir ~/dmt-build
  cd ~/dmt-build
  python3 -m venv venv-dmt
  ```

* Activate the newly created virtual environment:

  ```
  source venv-dmt/bin/activate
  ```

* Download DMT sources from GitHub:

  ```
  git clone https://github.com/Bertrand256/dash-masternode-tool
  ```
  > **Note**. At this point, you may be asked to install commandline developer tools, if you don't already 
  > have them on the computer. By clicking <Install> you will only install the toolset you need, but 
  > you can also install the entire XCode environment (<Get XCode> button) if you intend to use GUI 
  > development tools in the future.

* Install the requirements:

  ```
  cd dash-masternode-tool
  pip install -r requirements.txt
  ```

* Build the executable:

  ```
  pyinstaller --distpath=../dmt-dist/dist/mac --workpath=../dmt-dist/build/mac dash_masternode_tool.spec
  ```


Once the build has completed successfully, a compressed macOS executable file will be created in the `~/projects/dist/all` directory. An uncompressed app package (*DashMasternodeTool.app*) can be found in the `~/projects/dist/mac` directory.