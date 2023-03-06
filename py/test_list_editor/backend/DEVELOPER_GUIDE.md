# Test List Editor Backend Developer Guide

## Prerequisites

* Python3.10, You can get this through `sudo apt install python3.10`.
* virtualenv, You can get this through `python3.10 -m pip install virtualenv`.
* Set up environment by the following command.

    ```sh
    # (outside)
    scripts/setup-env.sh
    ```

    This command will create a folder `editor.venv` in `test_list_editor/backend`. The folder will
    be the virtualenv folder for the project.

* (Optional) You can also run this tool inside chroot. But we recommend to use this tool outside of
chroot. The process is exactly the same.

## Folder Structure

This is the folder for the test list editor backend server. The folder has the following structure:

* `scripts/`, the folder storing scripts for certain tasks.
