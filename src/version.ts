declare const __APP_VERSION__: string | undefined;
declare const __APP_ID__: string | undefined;
declare const __BUILD_VARIANT__: string | undefined;
declare const __BUILD_NUMBER__: string | undefined;
declare const __GIT_SHA__: string | undefined;
declare const __CI_RUN_URL__: string | undefined;
declare const __SIGNING_CERT_SHA256__: string | undefined;

export const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '2.4.1';
export const APP_NAME = 'Green Guide';
export const APP_NAME_DEV = 'Green Guide Dev';
export const APP_DISPLAY_VERSION = `v${APP_VERSION}`;
export const APP_ID = typeof __APP_ID__ !== 'undefined' ? __APP_ID__ : 'app.contrail.journal';
export const BUILD_VARIANT = typeof __BUILD_VARIANT__ !== 'undefined' ? __BUILD_VARIANT__ : 'web';
export const BUILD_NUMBER = typeof __BUILD_NUMBER__ !== 'undefined' ? __BUILD_NUMBER__ : 'local';
export const GIT_SHA = typeof __GIT_SHA__ !== 'undefined' ? __GIT_SHA__ : 'local';
export const CI_RUN_URL = typeof __CI_RUN_URL__ !== 'undefined' ? __CI_RUN_URL__ : '';
export const SIGNING_CERT_SHA256 = typeof __SIGNING_CERT_SHA256__ !== 'undefined' ? __SIGNING_CERT_SHA256__ : '';
