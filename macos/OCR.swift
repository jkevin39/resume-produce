import Foundation
import Vision
import ImageIO

func fail(_ message: String) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: ["error": message])
    FileHandle.standardOutput.write(data); exit(1)
}
let data = FileHandle.standardInput.readDataToEndOfFile()
guard data.count <= 4 * 1024 * 1024 else { fail("图片不能超过 4MB。") }
guard let source = CGImageSourceCreateWithData(data as CFData, nil),
      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
      let w = properties[kCGImagePropertyPixelWidth] as? Int,
      let h = properties[kCGImagePropertyPixelHeight] as? Int,
      w > 0, h > 0, w <= 24000000 / h else { fail("图片无效或超过 2400 万像素。") }
guard let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fail("无法解码图片。") }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
if #available(macOS 13.0, *) { request.revision = VNRecognizeTextRequestRevision3 }
let orientation = CGImagePropertyOrientation(rawValue: (properties[kCGImagePropertyOrientation] as? UInt32) ?? 1) ?? .up
do {
    try VNImageRequestHandler(cgImage: image, orientation: orientation).perform([request])
    let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: ["text": text]))
} catch { fail("本机文字识别失败，请换一张清晰截图后重试。") }
