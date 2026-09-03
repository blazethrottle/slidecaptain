import type { Deck } from "../api/client";

export type EditorState = { past: Deck[]; present: Deck; future: Deck[] };
export type EditorAction =
  | { type: "edit"; deck: Deck }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; deck: Deck };  // 충돌(412) 복구: 되돌리기 이력을 비우고 서버 덱으로 교체한다

const LIMIT = 100;

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "edit": {
      if (action.deck === state.present) return state;
      return {
        past: [...state.past.slice(-(LIMIT - 1)), state.present],
        present: action.deck,
        future: [],
      };
    }
    case "undo": {
      if (state.past.length === 0) return state;
      return {
        past: state.past.slice(0, -1),
        present: state.past[state.past.length - 1],
        future: [state.present, ...state.future],
      };
    }
    case "redo": {
      if (state.future.length === 0) return state;
      return {
        past: [...state.past, state.present],
        present: state.future[0],
        future: state.future.slice(1),
      };
    }
    case "reset": {
      return { past: [], present: action.deck, future: [] };
    }
  }
}
