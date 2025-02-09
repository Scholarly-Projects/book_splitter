# Setup Instructions for PDF Splitting Tool

To successfully run the Python tool for splitting PDF pages into left and right halves, please follow the instructions below to install the required software and dependencies.

## Step 1: Install Git and Bash

### 1A: Windows
1. **Download Git for Windows** (which includes Git Bash):
   - Go to the [Git for Windows website](https://gitforwindows.org/).
   - Download the installer and run it.
   - Follow the installation prompts, and make sure to select the option to use Git from the Windows Command Prompt.

### 1B: Mac
1. **Install Git using Homebrew**:
   - Open your Terminal.
   - If you don’t have Homebrew installed, run:
     ```bash
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
     ```
   - Once Homebrew is installed, run:
     ```bash
     brew install git
     ```

## Step 2: Install Python

### 2A: Windows
1. **Install Python 3:**
   - Go to the [Python official website](https://www.python.org/downloads/).
   - Download the latest version of Python (ensure to select the option to add Python to your PATH during installation).

### 2B: Mac
1. **Install Python 3 using Homebrew**:
   - Open your Terminal and run:
     ```bash
     brew install python
     ```

2. **Verify Python installation**:
   - Open your command line (or Terminal) and run:
     ```bash
     python3 --version
     ```
   - This should display the installed version of Python.

## Step 3: Create and Activate a Virtual Environment

1. **Create a Virtual Environment**:
   - In the command line, navigate to the cloned repository directory and run:
     ```bash
     python3 -m venv venv
     ```

2. **Activate the Virtual Environment**:
   - ### 2A: Windows
     ```bash
     venv\Scripts\activate
     ```
   - ### 2B: Mac
     ```bash
     source venv/bin/activate
     ```

## Step 4: Install Required Python Packages

1. **Install Packages**:
   - With the virtual environment activated, run the following command to install the required packages:
     ```bash
     pip install PyPDF2
     ```

## Step 5: Place Your PDF Files

1. **Place Your PDF Files**:
   - Place the PDF files you want to split into the `A` folder within the cloned repository.

## Step 6: Run the Python Script

1. **Run the Python Script**:
   - In the command line, navigate to the cloned repository directory and run:
     ```bash
     python script.py
     ```
    - Or simply go to `script.py` and press the play button on the top right corner of the screen in Visual Studio Code.

After following these steps, your PDF splitting tool should run successfully, and you will find the split PDFs in the `B` folder.
