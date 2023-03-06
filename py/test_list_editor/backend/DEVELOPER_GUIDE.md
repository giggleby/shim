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
* `api/`, the folder storing the endpoint processing logic.
* `tests/`, the folder storing unit test for the backend.

The `api/` folder has the following logic.

* The directory structure will follow how the api will be structured. Take the following structure
as an example:

  ```bash
  api
  |-- __init__.py
  |-- status.py
  `-- v1
      |-- __init__.py
      |-- items.py
  ```

* This means we will have `api/v1/items/` and `api/status` as our endpoint.

## Start the development process

You can run the dev server with the following command, and the default port for the dev server
is port `5000`.

```sh
# This will run flask server on port 5000
$ scripts/run-dev.sh
```

You can override the port settings by providing the parameter like below command.

```sh
# On Host (Outside)
# This will run flask server on port 6000
$ scripts/run-dev.sh 6000
```

You will see something like the following running in your terminal.

```sh
 * Serving Flask app 'cros.factory.test_list_editor.backend.main'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
Press CTRL+C to quit
 * Restarting with stat
 * Debugger is active!
 * Debugger PIN: 123-456-789
```

We can now access the server at `localhost:5000` on your host. If you are using
VSCode, you can try using
[thunder client](https://marketplace.visualstudio.com/items?itemName=rangav.vscode-thunder-client)
as a lightweight alternative to
[Postman](https://www.postman.com/). Or, you can just use the good old `curl` to do the work.

You can verify if the server is running or not by `curl localhost:5000/status`. This should respond
`{'status': 'ok'}`

## Run unittest

This will run unittests.

```sh
# On Host (Outside)
# This will run unittest
$ scripts/run-unittest.sh
```

## Endpoints

### Common Endpoints

* `/status` This is used to verify if the server is up and running.
