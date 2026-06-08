import { ImageResponse } from "next/og";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#2F5BFF",
          borderRadius: 14,
          color: "#FFFFFF",
          fontSize: 44,
          fontWeight: 700,
          letterSpacing: "-0.03em",
        }}
      >
        U
      </div>
    ),
    size,
  );
}
