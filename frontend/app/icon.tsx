import { ImageResponse } from "next/og";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

// Architechtura favicon — a golden spiral built from quarter-circle arcs through
// Fibonacci squares (1,1,2,3,5,8): an abstract "in alignment" mark that echoes
// the precision of good architecture. Blue stroke on a near-black tile.
const SPIRAL =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 13 8">' +
  '<path d="M 13 0 A 8 8 0 0 1 5 8 A 5 5 0 0 1 0 3 A 3 3 0 0 1 3 0 ' +
  'A 2 2 0 0 1 5 2 A 1 1 0 0 1 4 3 A 1 1 0 0 1 3 2" ' +
  'fill="none" stroke="#2F5BFF" stroke-width="0.62" ' +
  'stroke-linecap="round" stroke-linejoin="round"/></svg>';

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
          background: "#0B1220",
          borderRadius: 14,
        }}
      >
        <img
          width={44}
          height={27}
          src={`data:image/svg+xml;utf8,${encodeURIComponent(SPIRAL)}`}
        />
      </div>
    ),
    size,
  );
}
