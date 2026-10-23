/*
    Copyright (c) 2024 Sundsvalls Kommun
*/

import { json } from "@sveltejs/kit";

export const GET = async () => {
  return json({
    status: "OK",
    timestamp: new Date().toISOString(),
    service: "frontend-web"
  });
};
