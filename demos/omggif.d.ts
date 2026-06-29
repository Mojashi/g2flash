declare module "omggif" {
  export class GifReader {
    constructor(buf: Uint8Array);
    width: number;
    height: number;
    numFrames(): number;
    frameInfo(frame: number): {
      x: number;
      y: number;
      width: number;
      height: number;
      disposal: number;
      delay: number;
    };
    // Composites frame `frame` onto `pixels` (width*height*4 RGBA), honoring
    // transparency. Call frames in order with the same buffer for compositing.
    decodeAndBlitFrameRGBA(frame: number, pixels: Uint8Array): void;
  }
}
