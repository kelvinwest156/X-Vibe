import { initializeApp, getApps, getApp, FirebaseApp } from "firebase/app";
import {
  getAuth,
  Auth,
  GoogleAuthProvider,
  TwitterAuthProvider,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  User,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || "",
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || "",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || "",
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.projectId
);

let app: FirebaseApp | null = null;
let auth: Auth | null = null;

if (typeof window !== "undefined") {
  if (isFirebaseConfigured) {
    app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
    auth = getAuth(app);
  }
}

export { auth };

export const googleProvider = new GoogleAuthProvider();
export const twitterProvider = new TwitterAuthProvider();

export async function loginWithGoogle(): Promise<{ user: User | null; token: string | null }> {
  if (!auth) {
    throw new Error("Firebase is not configured. Please add your NEXT_PUBLIC_FIREBASE_* credentials to .env.local.");
  }
  const result = await signInWithPopup(auth, googleProvider);
  const token = await result.user.getIdToken();
  return { user: result.user, token };
}

export async function loginWithTwitter(): Promise<{ user: User | null; token: string | null }> {
  if (!auth) {
    throw new Error("Firebase is not configured. Please add your NEXT_PUBLIC_FIREBASE_* credentials to .env.local.");
  }
  const result = await signInWithPopup(auth, twitterProvider);
  const token = await result.user.getIdToken();
  return { user: result.user, token };
}

export async function loginWithEmail(email: string, pass: string): Promise<{ user: User | null; token: string | null }> {
  if (!auth) {
    throw new Error("Firebase is not configured. Please add your NEXT_PUBLIC_FIREBASE_* credentials to .env.local.");
  }
  const result = await signInWithEmailAndPassword(auth, email, pass);
  const token = await result.user.getIdToken();
  return { user: result.user, token };
}

export async function registerWithEmail(email: string, pass: string): Promise<{ user: User | null; token: string | null }> {
  if (!auth) {
    throw new Error("Firebase is not configured. Please add your NEXT_PUBLIC_FIREBASE_* credentials to .env.local.");
  }
  const result = await createUserWithEmailAndPassword(auth, email, pass);
  const token = await result.user.getIdToken();
  return { user: result.user, token };
}

export async function logoutUser(): Promise<void> {
  if (auth) {
    await signOut(auth);
  }
}

export function subscribeToAuth(callback: (user: User | null) => void) {
  if (!auth) {
    callback(null);
    return () => {};
  }
  return onAuthStateChanged(auth, callback);
}
