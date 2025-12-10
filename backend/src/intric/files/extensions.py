from intric.files.audio import AudioMimeTypes
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes

MIMETYPE_EXTENSIONS_MAPPER = {
    # TEXT
    TextMimeTypes.MD.value: [".md", ".markdown", ".mdown", ".markdn"],
    TextMimeTypes.TXT.value: [".txt", ".text"],
    TextMimeTypes.PDF.value: [".pdf"],
    TextMimeTypes.DOCX.value: [".docx"],
    TextMimeTypes.TEXT_CSV.value: [".csv"],
    TextMimeTypes.APP_CSV.value: [".csv"],
    TextMimeTypes.PPTX.value: [".pptx"],
    TextMimeTypes.XLSX.value: [".xlsx"],
    TextMimeTypes.XLS.value: [".xls"],
    # Legacy formats (for detection/rejection)
    TextMimeTypes.DOC.value: [".doc"],
    TextMimeTypes.PPT.value: [".ppt"],
    # AUDIO
    AudioMimeTypes.M4A.value: [".m4a"],
    AudioMimeTypes.OGG.value: [".oga", ".ogg", ".spx", ".opus"],
    AudioMimeTypes.WAV.value: [".wav"],
    AudioMimeTypes.MPEG.value: [".mp3", ".mp2", ".mpga", ".mp2a", ".m2a", ".m3a"],
    AudioMimeTypes.MP3.value: [".mp3"],
    AudioMimeTypes.MP4.value: [".mp4"],
    AudioMimeTypes.MP4A.value: [".m4a"],
    AudioMimeTypes.WEBM.value: [".webm"],
    AudioMimeTypes.WEBA.value: [".weba"],
    # IMAGE
    ImageMimeTypes.PNG.value: [".png"],
    ImageMimeTypes.JPEG.value: [".jpeg", ".jpg", ".jpe"],
}
