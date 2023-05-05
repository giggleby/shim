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
* `schema/`, the folder storing the data models used to validate the parameters, body, and response.
* `models/`, the folder storing the data models used by each controller.
* `controller/`, the folder for interacting with different "models"(resources).
* `middleware/`, the folder for storing the decorator middleware.

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

## Testing out endpoints

After you have successfully start the Flask instance, you can now use `curl` or
[thunder client](https://marketplace.visualstudio.com/items?itemName=rangav.vscode-thunder-client)
to make request to the server.

In Flask, we use blueprints to specify endpoints in a structural way. Take the following as an
example. The endpoint in below example does not exist in the actual server. They are here just for
demonstration purposes.

```python
bp = Blueprint('users', __name__, url_prefix='/api/v1/resource')
...

@bp.route('/', methods=['PUT'])
@middleware.ValidateRequest(blob.ResourcesRequest)
@middleware.ValidateResponse(blob.CreateResourceResponse)
def CreateResources(request_body):
  # process files
  return blob.CreateResourceResponse(...)
```

The code means we can access the api at `localhost:5000/api/v1/resource` by "PUT" method.
It expects the request body to be in the form of `ResourcesRequest` and a response to be in the form
of `CreateResourceResponse`.

The request and response shape can be found in `schema/blob.py`.
The file names in `schema` specify what data models are used in the corresponding file
inside `api/v1/*`.

The following is an example of the data model specified by [Pydantic](https://docs.pydantic.dev/).

```python
class ResourceObject(BaseModel):
  resource_name: str
  data: Dict

class ResourcesRequest(BaseModel):
  blobs: List[ResourceObject]
```

This is equivalent to the following representation.

```json
{
  "blobs": [
    {
      "resource_name": "xxx",
      "data": {
        ...
      }
    },
    {
      "resource_name": "yyy",
      "data": {
        ...
      }
    },
    ...
  ]
}
```

Now to make a request, if you use any Postman like interface, set the endpoint to
`localhost:5000/api/v1/resource`, request method to **PUT** and body to json. A sample json data
like the following would work.

```json
{
  "blobs": [
    {
      "resource_name": "www",
      "data": {
        "something": true
      }
    },
    {
      "resource_name": "xxx",
      "data": {
        "something": true
      }
    }
  ]
}
```

Or, if you use `curl`

```sh
curl -X PUT \
  'localhost:5000/api/v1/resource' \
  --header 'Content-Type: application/json' \
  --data-raw '{
  "blobs": [
    {
      "resource_name": "www",
      "data": {
        "something": true
      }
    },
    {
      "resource_name": "xxx",
      "data": {
        "something": true
      }
    }
  ]
}'
```

After making a successful request, you should see the response

```json
{
  "blob_status": {},
  "message": "",
  "status": "success"
}
```

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
