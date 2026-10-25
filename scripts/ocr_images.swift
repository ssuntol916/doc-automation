// Local-only OCR with Apple Vision. OCR observations require source-image review.
import Foundation
import Vision

guard CommandLine.arguments.count == 3 else {
    fputs("Usage: ocr_images <asset-directory> <output-json>\n", stderr)
    exit(2)
}
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
let fm = FileManager.default
let extensions: Set<String> = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif"]
let files = try fm.contentsOfDirectory(at: input, includingPropertiesForKeys: nil).filter { extensions.contains($0.pathExtension.lowercased()) }.sorted { $0.lastPathComponent < $1.lastPathComponent }
let probe = VNRecognizeTextRequest()
let supported = try probe.supportedRecognitionLanguages()
let languages = ["ko-KR", "en-US"].filter { supported.contains($0) }
var records: [[String: Any]] = []
for (index, file) in files.enumerated() {
    autoreleasepool {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = languages
        request.usesLanguageCorrection = false
        var record: [String: Any] = ["asset": file.lastPathComponent, "path": file.path]
        do {
            try VNImageRequestHandler(url: file, options: [:]).perform([request])
            record["observations"] = (request.results ?? []).compactMap { observation -> [String: Any]? in
                guard let text = observation.topCandidates(1).first else { return nil }
                let b = observation.boundingBox
                return ["text": text.string, "confidence": text.confidence, "bounding_box_bottom_left": [b.origin.x, b.origin.y, b.size.width, b.size.height]]
            }
        } catch {
            record["error"] = String(describing: error)
        }
        records.append(record)
    }
    if (index + 1) % 20 == 0 {
        fputs("OCR \(index + 1)/\(files.count)\n", stderr)
    }
    // Persist a checkpoint after every image; reruns may inspect completed work.
    let result: [String: Any] = ["engine": "Apple Vision VNRecognizeTextRequest", "scope": "Local OCR observations; recognition is not factual verification", "languages": languages, "completed": records.count == files.count, "expected_assets": files.count, "records": records]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: output, options: .atomic)
}
print("OCR complete: \(records.count) assets")
