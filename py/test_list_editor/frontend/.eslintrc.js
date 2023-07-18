// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

module.exports = {
    "env": {
        "browser": true,
        "es2021": true,
        "jest": true
    },
    "extends": [
        "eslint:recommended",
        "plugin:@typescript-eslint/recommended",
        "plugin:@typescript-eslint/recommended-requiring-type-checking",
        "plugin:react/recommended",
        "react-app",
        "react-app/jest",
        "prettier"
    ],
    "ignorePatterns": [
        "coverage/**"
    ],
    "parserOptions": {
        "ecmaVersion": "latest",
        "sourceType": "module",
        "project": ["./tsconfig.json"],
        "tsconfigRootDir": __dirname
    },
    "plugins": [
        "react",
        "@typescript-eslint",
        "jest"
    ],
    "rules": {
        "react/react-in-jsx-scope": "off",
        "@typescript-eslint/no-misused-promises": [2, {
            "checksVoidReturn": {
                "attributes": false
            }
        }]
    },
    "root": true
}
