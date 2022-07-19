# ChromeOS Factory Developer VSCode configuration files

This folder contains VSCode configuration files that are useful for
ChromeOS Factory development and ChromeOS factory team.
(e.g, non-factory repositories)

## Installation

* Run `./devtools/vscode/setup.sh ${workspaceFolder}` outside chroot to install
  `.vscode/settings.json` under `${workspaceFolder}`. Examples:
  * If you want to use src/platform/factory as workspaceFolder:
    ```
    cd path/to/src/platform/factory
    workspaceFolder=.
    ./devtools/vscode/setup.sh ${workspaceFolder}
    code ${workspaceFolder}
    ```
  * If you want to use src/private-overlays as workspaceFolder:
    ```
    cd path/to/src/platform/factory
    workspaceFolder=../../private-overlays
    ./devtools/vscode/setup.sh ${workspaceFolder}
    code ${workspaceFolder}
    ```
  * If you want to use src/private-overlays/overlay-${BOARD}-private as
    workspaceFolder:
    ```
    cd path/to/src/platform/factory
    workspaceFolder=../../private-overlays/overlay-${BOARD}-private
    ./devtools/vscode/setup.sh ${workspaceFolder}
    code ${workspaceFolder}
    ```

## Recommended Extensions

* Code Navigation (vikas.code-navigation)
* Instant Markdown (dbankier.vscode-instant-markdown)
* Trailing Spaces (shardulm94.trailing-spaces)
* Python (ms-python.python)
