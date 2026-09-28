import Cocoa
let output = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
 for scale in [1, 2] {
  let pixels = size * scale
  let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
  NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
  let transform=AffineTransform(scale:CGFloat(pixels)/512); (transform as NSAffineTransform).concat()
  NSColor(calibratedRed:0.08,green:0.30,blue:0.50,alpha:1).setFill()
  NSBezierPath(roundedRect:NSRect(x:20,y:20,width:472,height:472),xRadius:100,yRadius:100).fill()
  NSColor.white.setFill()
  NSBezierPath(roundedRect:NSRect(x:126,y:82,width:260,height:348),xRadius:20,yRadius:20).fill()
  NSColor(calibratedRed:0.12,green:0.39,blue:0.62,alpha:1).setFill()
  for (y,width) in [(338,100),(278,180),(228,180),(178,140)] {
   NSBezierPath(roundedRect:NSRect(x:166,y:y,width:width,height:18),xRadius:7,yRadius:7).fill()
  }
  NSGraphicsContext.restoreGraphicsState()
  let suffix=scale==2 ? "@2x" : ""
  try bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
 }
}
