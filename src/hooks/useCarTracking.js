import { useEffect, useRef, useState } from 'react'

// Simple in-browser car tracking for the recorded pursuit video.
// It finds dark, car-sized blobs on the road and boxes the one nearest
// the center of the frame. Tuned for the demo footage; a real detector
// (e.g. a backend model) should replace findCenteredCar later.

const LABEL = 'target acquired'
const BOX_COLOR = '#ff2b2b'
const SAMPLE_WIDTH = 180
const SMOOTHING = 0.18
const BOX_PADDING = { x: 8, y: 6 }

function isTrackingWindow(video) {
  // Only track during the second half of the video.
  return video.duration > 0 && video.currentTime >= video.duration / 2
}

function findCenteredCar(video, sampleCanvas, sampleContext) {
  const width = SAMPLE_WIDTH
  const height = Math.round(width * (video.videoHeight / video.videoWidth))
  sampleCanvas.width = width
  sampleCanvas.height = height
  sampleContext.drawImage(video, 0, 0, width, height)

  const pixels = sampleContext.getImageData(0, 0, width, height).data
  const mask = new Uint8Array(width * height)
  const visited = new Uint8Array(width * height)
  const roadTop = Math.floor(height * 0.44)
  const roadBottom = Math.floor(height * 0.88)

  // Mark dark, low-saturation pixels in the road area.
  for (let y = roadTop; y < roadBottom; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4
      const r = pixels[i]
      const g = pixels[i + 1]
      const b = pixels[i + 2]
      const brightness = (r + g + b) / 3
      const saturation = Math.max(r, g, b) - Math.min(r, g, b)
      if (brightness < 85 && saturation < 75) mask[y * width + x] = 1
    }
  }

  let best = null
  let bestScore = 0

  // Group marked pixels into blobs and keep the most centered car-shaped one.
  for (let y = roadTop; y < roadBottom; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const start = y * width + x
      if (!mask[start] || visited[start]) continue

      const stack = [start]
      visited[start] = 1
      let minX = x
      let maxX = x
      let minY = y
      let maxY = y
      let area = 0

      while (stack.length) {
        const current = stack.pop()
        const cx = current % width
        const cy = Math.floor(current / width)
        area += 1
        minX = Math.min(minX, cx)
        maxX = Math.max(maxX, cx)
        minY = Math.min(minY, cy)
        maxY = Math.max(maxY, cy)

        for (const next of [current - 1, current + 1, current - width, current + width]) {
          if (next < 0 || next >= mask.length || visited[next] || !mask[next]) continue
          if (Math.abs((next % width) - cx) > 1) continue
          visited[next] = 1
          stack.push(next)
        }
      }

      const boxWidth = maxX - minX + 1
      const boxHeight = maxY - minY + 1
      const aspect = boxWidth / boxHeight
      const isCarShaped = area > 28 && area < width * height * 0.08
        && boxWidth > 10 && boxHeight > 6 && aspect > 0.7 && aspect < 4.8
      if (!isCarShaped) continue

      const offCenterX = Math.abs(minX + boxWidth / 2 - width / 2) / (width / 2)
      const offCenterY = Math.abs(minY + boxHeight / 2 - height * 0.66) / height
      const score = (1 - Math.min(1, offCenterX + offCenterY * 0.35)) * 1000 + Math.min(1, area / 900) * 100

      if (score > bestScore) {
        bestScore = score
        best = { minX, maxX, minY, maxY, sampleWidth: width, sampleHeight: height }
      }
    }
  }

  return best
}

// Map a box from sample coordinates to on-screen coordinates,
// accounting for object-fit: cover cropping.
function toScreenBox(box, video) {
  const viewWidth = video.clientWidth
  const viewHeight = video.clientHeight
  const scale = Math.max(viewWidth / video.videoWidth, viewHeight / video.videoHeight)
  const offsetX = (viewWidth - video.videoWidth * scale) / 2
  const offsetY = (viewHeight - video.videoHeight * scale) / 2
  const toX = (x) => (x / box.sampleWidth) * video.videoWidth * scale + offsetX
  const toY = (y) => (y / box.sampleHeight) * video.videoHeight * scale + offsetY

  return {
    x: toX(box.minX) - BOX_PADDING.x,
    y: toY(box.minY) - BOX_PADDING.y,
    width: toX(box.maxX + 1) - toX(box.minX) + BOX_PADDING.x * 2,
    height: toY(box.maxY + 1) - toY(box.minY) + BOX_PADDING.y * 2,
  }
}

function drawBox(context, box) {
  context.strokeStyle = BOX_COLOR
  context.lineWidth = 3
  context.beginPath()
  context.roundRect(box.x, box.y, box.width, box.height, 14)
  context.stroke()

  context.fillStyle = BOX_COLOR
  context.font = '600 12px Inter, system-ui, sans-serif'
  context.fillText(LABEL, box.x, Math.max(14, box.y - 6))
}

export function useCarTracking() {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const [carDetected, setCarDetected] = useState(false)

  useEffect(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return undefined

    const context = canvas.getContext('2d')
    const sampleCanvas = document.createElement('canvas')
    const sampleContext = sampleCanvas.getContext('2d', { willReadFrequently: true })
    let frameId = 0
    let lastVideoTime = -1
    let rawBox = null
    let smoothedBox = null
    let detected = false

    const syncCanvasSize = () => {
      const ratio = window.devicePixelRatio || 1
      const width = Math.round(video.clientWidth * ratio)
      const height = Math.round(video.clientHeight * ratio)
      if (canvas.width === width && canvas.height === height) return
      canvas.width = width
      canvas.height = height
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
    }

    const tick = () => {
      syncCanvasSize()

      // Only re-analyze when the video has moved to a new frame.
      if (video.currentTime !== lastVideoTime && video.videoWidth) {
        lastVideoTime = video.currentTime
        rawBox = isTrackingWindow(video) ? findCenteredCar(video, sampleCanvas, sampleContext) : null
      }

      if (Boolean(rawBox) !== detected) {
        detected = Boolean(rawBox)
        setCarDetected(detected)
      }

      context.clearRect(0, 0, video.clientWidth, video.clientHeight)

      if (rawBox) {
        const next = toScreenBox(rawBox, video)
        smoothedBox = smoothedBox
          ? {
              x: smoothedBox.x + (next.x - smoothedBox.x) * SMOOTHING,
              y: smoothedBox.y + (next.y - smoothedBox.y) * SMOOTHING,
              width: smoothedBox.width + (next.width - smoothedBox.width) * SMOOTHING,
              height: smoothedBox.height + (next.height - smoothedBox.height) * SMOOTHING,
            }
          : next
        drawBox(context, smoothedBox)
      } else {
        smoothedBox = null
      }

      frameId = window.requestAnimationFrame(tick)
    }

    frameId = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(frameId)
  }, [])

  return { videoRef, canvasRef, carDetected }
}
