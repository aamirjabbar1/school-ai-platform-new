import { useMemo } from 'react';
import VideoTile from './VideoTile';
import Whiteboard from './Whiteboard';
import BookViewer from './BookViewer';
import VideoStage from './VideoStage';
import { API_ORIGIN } from '../../services/api';

// ─── The main teaching area (spec §11) ────────────────────────────────────────
//
// Whatever the teacher is showing fills this space, and every student's screen
// follows automatically — book, board, video, shared screen or camera. Students never
// choose what to watch; a nine-year-old should not have to work out which tile
// is the lesson.
//
// The surfaces below all size themselves with `w-full h-full`, which only
// means anything inside a box of a known height. The classroom's stage is a
// flex item whose height comes from `min-height` and from growing, so its own
// height stays `auto` — and a percentage resolved against `auto` is not 45vh,
// it is nothing. On a phone that made every surface here exactly nothing tall:
// a video that was loading, playing and unmuted, and 0 pixels high. A desktop
// escaped it, because there the stage is a *row* flex item and gets stretched
// to a real height. Filling this positioned box asks no question that `auto`
// can answer.
export default function Stage(props) {
  return (
    <div className="absolute inset-0">
      <Surface {...props} />
    </div>
  );
}

function Surface({
  classroom, sessionId, editable, boardRef, onSaveBoard, savingBoard,
}) {
  const {
    stage, remoteVideo, remoteScreen, localVideo, boardStrokes, bookAnnotations,
    liveStrokes, board, boardPageCount, resourceToken, teacherPresent,
    addStroke, sendStrokeProgress, clearSurface, undoStroke, setBoardPage, addBoardPage,
    changeStage, presentPage,
  } = classroom;

  const bookState = stage.state?.book || {};

  // pdf.js fetches the file itself and cannot carry our Authorization header,
  // so the URL carries a short-lived token scoped to this one classroom.
  const fileUrl = useMemo(() => {
    if (!bookState.document_id || !resourceToken) return null;
    return `${API_ORIGIN}/online-classes/${sessionId}/resources/${bookState.document_id}/file`
      + `?rt=${encodeURIComponent(resourceToken)}`;
  }, [bookState.document_id, sessionId, resourceToken]);

  const teacherVideo = remoteVideo || localVideo;

  switch (stage.mode) {
    case 'whiteboard':
      return (
        <Whiteboard
          ref={boardRef}
          editable={editable}
          strokes={boardStrokes}
          liveStrokes={editable ? [] : liveStrokes}
          onStroke={addStroke}
          onStrokeProgress={sendStrokeProgress}
          onClear={clearSurface}
          onUndo={undoStroke}
          pageIndex={board.pageIndex}
          pageCount={boardPageCount}
          onPageChange={editable ? setBoardPage : undefined}
          onAddPage={editable ? addBoardPage : undefined}
          onSave={editable ? onSaveBoard : undefined}
          saving={savingBoard}
        />
      );

    case 'book':
      return fileUrl ? (
        <BookViewer
          fileUrl={fileUrl}
          kind={bookState.kind || 'pdf'}
          page={bookState.page || 1}
          zoom={bookState.zoom || 1}
          editable={editable}
          annotations={editable ? bookAnnotations : [...bookAnnotations, ...liveStrokes]}
          onStroke={addStroke}
          onStrokeProgress={sendStrokeProgress}
          onClearAnnotations={clearSurface}
          onUndoAnnotation={undoStroke}
          onPageChange={editable ? presentPage : undefined}
          onZoomChange={editable ? (zoom) => changeStage('book', { zoom }) : undefined}
        />
      ) : (
        <EmptyStage message="No book is open." />
      );

    case 'video':
      return (
        <VideoStage
          video={stage.state?.video}
          editable={editable}
          sync={classroom.videoSync}
          lowBandwidth={classroom.lowBandwidth}
          onReport={editable ? classroom.reportVideo : undefined}
          onProgress={editable ? classroom.sendVideoProgress : undefined}
          onStop={editable ? () => changeStage('camera', null) : undefined}
        />
      );

    case 'screen':
      return (
        <VideoTile
          track={remoteScreen || (stage.state?.screen?.source === 'document_camera' ? teacherVideo : null)}
          muted
          placeholder={
            stage.state?.screen?.source === 'document_camera'
              ? 'Pointing the camera at the book…'
              : 'Starting the shared screen…'
          }
          className="w-full h-full"
        />
      );

    default:
      return (
        <VideoTile
          track={teacherVideo}
          mirrored={editable && !classroom.docCameraOn}
          // "Waiting" is only true if the teacher is not in the room. A teacher
          // teaching from a computer with no webcam is present, not absent, and
          // telling a class otherwise makes a working lesson look broken.
          placeholder={
            editable
              ? 'Your camera is off'
              : teacherPresent
                ? "Your teacher's camera is off"
                : 'Waiting for your teacher'
          }
          className="w-full h-full"
        />
      );
  }
}

function EmptyStage({ message }) {
  return (
    <div className="w-full h-full flex items-center justify-center rounded-2xl bg-surface-3 text-muted text-sm">
      {message}
    </div>
  );
}
