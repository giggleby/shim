# Test List Editor Frontend Developer Guide

This is the frontend for the test list editor. It is created with
[React](https://reactjs.org/docs/getting-started.html).

## Prerequisites

* `node`, you can alternatively use [nvm](https://github.com/nvm-sh/nvm) to manage your node
version. We use node v18 and npm v8 at the time this project is created.

## Folder structure

The folder structure is scaffolded by `create-react-app`. The folder structure can be found
[here](https://create-react-app.dev/docs/folder-structure)

* `src/`, Stores the source code for the frontend. All the source code (e.g. `.tsx`, `.css`, etc.)
should be placed in this folder or it would not be built.
* `public/`, Stores the static files for the web page. Files like `index.html`, pictures will
be placed here.
* `node_modules/`, Stores the node module for the frontend.
* `.env`, Stores the configuration for running the **dev** frontend.

## Start the dev frontend server

* Run `npm ci` to install the dependent packages.
* The frontend default runs on port `5100`. If you want to change the port setting, you can
modify the `.env` file located in this folder.
* If you want the page to show up in your browser, you will
need to set up [port forwarding](https://www.ssh.com/academy/ssh/tunneling-example) from your
remote server to your local web browser.

```sh
# start the dev frontend server
npm run start
# Now the frontend is running on port 5100.
# Go to localhost:5100 to see the webpage.
```

## Production container

* The production container uses a nginx instance to serve the static files.
* The default port for nginx inside the container is 6000 and should not be modified, but you can
bind it to a different port on your host by specifying it when running the container using the
PORT argument as below example. However, if you need to modify the port inside the container
itself, you will need to edit the Dockerfile and nginx.conf files.

```sh
# Builds the container
docker build -t dev-editor-fe .

# Runs the container
# Change PORT variable to change the bind location
PORT=6000
docker run -p ${PORT}:6000 dev-editor-fe
```
