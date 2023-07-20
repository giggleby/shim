// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import { ILandingCardProps, LandingCard } from "./landing_card";

// TODO: Setup a "recent" section in the landing page.
export function LandingHeader() {
  const uploadTestListCard: ILandingCardProps = {
    title: "Upload Test List",
    ctaLink: "/upload",
    ctaText: "Upload",
    description: "Upload your local test list to the tool.",
  };
  const startNewCard: ILandingCardProps = {
    title: "Start New Test List",
    ctaLink: "/edit",
    ctaText: "Start",
    description: "Use the default test list to start editing.",
  };

  return (
    <Box
      textAlign="center"
      sx={{ mt: "70px" }}
    >
      <Stack
        direction="row"
        spacing={2}
        divider={
          <Divider
            orientation="vertical"
            flexItem
          />
        }
        justifyContent="center"
      >
        <LandingCard {...uploadTestListCard} />
        <LandingCard {...startNewCard} />
      </Stack>
    </Box>
  );
}
