## Building DashMasternodeTool executable on Mac

The procedure will be carried out using the Mac terminal application, so it should be run first.

* Install the *homebrew* package, by invoking the following command from your terminal app:

  ```
  /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
  ```

  Installation takes about 5 minutes to complete.

* Install Python 3:

  ```
  brew install python3
  ```

* After the installation process completes, make sure, that the Python version installed is 3.6 or newer. DMT won't compile on older Python versions, event if it's version 3:

  ```
  python3 --version
  ```

  as a result you should get a result like this:

  `Python 3.6.4`

* Install *virtualenv*:

  ```
  pip3 install virtualenv
  ```

* Create Python virtual environment dedicated to DMT:

  ```
  cd ~
  mkdir projects
  mkdir projects/virtualenvs
  cd projects/virtualenvs
  virtualenv -p python3 dmt
  ```

* Activate the new virtual environment:

  ```
  source dmt/bin/activate
  ```

* Download DashMasternodeTool sources from Github:

  ```
  cd ~/projects
  git clone https://github.com/Bertrand256/dash-masternode-tool
  ```

* Install the DMT's Python prerequisites:

  ```
  cd dash-masternode-tool
  pip install -r requirements.txt
  ```

* Build the DMT executable:

  ```
  pyinstaller --distpath=../dist/mac --workpath=../build/mac dash_masternode_tool.spec
  ```


As a result of a successful build, a compressed Mac executable file is created in the ***~/projects/dist/all*** directory.  
An uncompressed app package (*DashMasernodeTool.app*) can be found in the ***~/projects/dist/mac*** directory. 