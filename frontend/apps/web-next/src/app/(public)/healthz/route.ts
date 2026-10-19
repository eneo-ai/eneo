export function GET() {
  return Response.json({
    status: "OK",
    timestamp: new Date().toISOString(),
    service: "frontend-web-next"
  });
}
