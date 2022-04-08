# Easy Bundle Creation

[TOC]

## Introduction

Easy Bundle Creation is a backend service that accepts RPC calls, creates the
factory bundles and supports downloading the created bundles.

To see the full prerequisites and setup, check go/cros-bundle-creator-setup.

## File location

### ChromeOS repository

* `$(factory-repo)/py/bundle_creator` contains the main codebase.
* `$(factory-repo)/deploy/bundle_creator.sh` is the helper script to
  deploy the project.
* `$(factory-private-repo)/config/bundle_creator` contains all the
  confidential configurations.


## Development Guide

### Prerequisites

Install Docker
  - go/installdocker

Install dependencies:
```
sudo apt-get install protobuf-compiler google-cloud-sdk
```

### Build & Deploy

To deploy the app engine, run:

```
(factory-repo)$ ./deploy/bundle_creator.sh deploy-appengine ${deployment_type}
(factory-repo)$ ./deploy/bundle_creator.sh deploy-appengine-legancy ${deployment_type}
```

To deploy the compute engine, run:

```
(factory-repo)$ ./deploy/bundle_creator.sh deploy-docker ${deployment_type}
```

To access the VM, run:
```
# SSH ino the VM
(factory-repo)$ ./deploy/bundle_creator.sh ssh-vm ${deployment_type}

# Login the docker
(inside VM)$ docker exec -it bundle-docker-1 sh
```

### Testing

#### Unittest

`make -C $(factory-repo) test` ignores all unittest modules related to Easy
Bundle Creation. Instead, developers should trigger the tests by the helper
script as follow:

```
(factory-repo)$ ./deploy/bundle_creator.sh test-docker
```

The `test-docker` command trigger the tests under `./py/bundle_creator/docker`
and `./py/bundle_creator/connector`.

#### Manual test

To run `docker/worker.py` in local, run:
```
(factory-repo)$ ./deploy/bundle_creator.sh run-docker ${deployment_type}
```

### Sending request

```
(factory-repo)$ cat > /tmp/create_bundle.txt << EOF
board: "cherry"
project: "tomato"
phase: "pvt"
toolkit_version: "14195.0.0"
test_image_version: "14195.0.0"
release_image_version: "14195.0.0"
email: "$(whoami)@google.com"
EOF
(factory-repo)$ ./deploy/bundle_creator.sh request ${deployment_type} < /tmp/create_bundle.txt
```
