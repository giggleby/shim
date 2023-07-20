// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Typography from "@mui/material/Typography";
import { Link } from "react-router-dom";

export interface ILandingCardProps {
  title: string;
  description: string;
  ctaText: string;
  ctaLink: string;
}

export function LandingCard({
  title,
  description,
  ctaText,
  ctaLink,
}: ILandingCardProps) {
  return (
    <Card sx={{ width: "400px" }}>
      <CardHeader>{title}</CardHeader>
      <CardContent>
        <Typography
          variant="h6"
          align="center"
          gutterBottom
        >
          {title}
        </Typography>
        <Typography sx={{ height: 65 }}>{description}</Typography>
        <Box
          textAlign="center"
          margin={1.5}
        >
          <Link to={ctaLink}>
            <Button variant="contained">{ctaText}</Button>
          </Link>
        </Box>
      </CardContent>
    </Card>
  );
}
