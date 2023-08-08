// Copyright 2020 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

module.exports = {
  // The root of your source code, typically /src
  // `<rootDir>` is a token Jest substitutes
  roots: ["<rootDir>/src"],

  // Jest transformations -- this adds support for TypeScript
  // using ts-jest
  transform: {
    "^.+\\.tsx?$": "ts-jest"
  },

  // Runs special logic, such as cleaning up components
  // when using React Testing Library and adds special
  // extended assertions to Jest
  setupFilesAfterEnv: [
    "@testing-library/jest-dom/extend-expect"
  ],

  // Test spec file resolution pattern
  // Matches parent folder `__tests__` and filename
  // should contain `test` or `spec`.
  testRegex: "(/.*(test|spec))\\.tsx?$",

  // Module file extensions for importing
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json", "node"],

  // An array of directory names to be searched recursively up from the
  // requiring module's location.
  moduleDirectories: ["node_modules", "src"],

  // A map from regular expressions to module names or to arrays of module
  // names that allow to stub out resources.
  moduleNameMapper: {
    '@app/(.*)': '<rootDir>/src/$1',
    '@common/(.*)': '<rootDir>/src/common/$1',
  },

  // Use a Jest test results processor for generating a summary in HTML.
  reporters: [
    "default",
    [
      "jest-html-reporters", {
        publicPath: "report"
      }
    ]
  ]
};
