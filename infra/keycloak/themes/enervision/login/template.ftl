<#--
  Mise en page commune à toutes les pages de connexion du realm (connexion, mot de passe
  oublié, erreur...) : la marque EnerVision, et une Card de shadcn.
  Même macro que le template.ftl du thème de base, que les autres pages appellent, sans
  ce que le realm n'utilise pas (fournisseurs d'identité, autre moyen de connexion,
  passkeys) ; « subtitle » en plus, pour le sous-titre de la carte (login.ftl).
-->
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html lang="${lang}">

<head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${msg("loginTitle",(realm.displayName!''))}</title>
    <link rel="icon" href="${url.resourcesPath}/img/favicon.ico" />
    <#-- Même clé et même règle que front/index.html (le front est à la même adresse, donc
         même localStorage) : le thème choisi dans l'application, sinon celui du système -->
    <script>
        try {
            var theme = localStorage.getItem('enervision-theme')
            if (theme === 'dark' || ((!theme || theme === 'auto') && matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.classList.add('dark')
            }
        } catch (e) {}
    </script>
    <link href="${url.resourcesPath}/css/enervision.css" rel="stylesheet" />
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <#-- Script du thème de base : connexion faite dans un autre onglet -->
    <script type="module">
        import { startSessionPolling } from "${url.resourcesPath}/js/authChecker.js";

        startSessionPolling(
            "${url.ssoLoginInOtherTabsUrl?no_esc}"
        );
    </script>
    <#if authenticationSession??>
        <script type="module">
            import { checkAuthSession } from "${url.resourcesPath}/js/authChecker.js";

            checkAuthSession(
                "${authenticationSession.authSessionIdHash}"
            );
        </script>
    </#if>
</head>

<body class="ev-page ${bodyClass}" data-page-id="login-${pageId}">
<main class="ev-shell">
    <div id="kc-header" class="ev-brand">${realm.displayName!'EnerVision'}</div>

    <div class="ev-card" data-slot="card">
        <header class="ev-card-header" data-slot="card-header">
            <#if auth?has_content && auth.showUsername() && !auth.showResetCredentials()>
                <#nested "show-username">
                <h1 id="kc-page-title" class="ev-card-title"><#nested "header"></h1>
                <div id="kc-username" class="ev-attempted-username">
                    <span id="kc-attempted-username">${auth.attemptedUsername}</span>
                    <a id="reset-login" class="ev-link" href="${url.loginRestartFlowUrl}" aria-label="${msg("restartLoginTooltip")}" title="${msg("restartLoginTooltip")}">
                        <i class="${properties.kcResetFlowIcon!}" aria-hidden="true"></i>
                    </a>
                </div>
            <#else>
                <h1 id="kc-page-title" class="ev-card-title"><#nested "header"></h1>
            </#if>
            <#assign subtitle><#nested "subtitle"></#assign>
            <#if subtitle?markup_string?trim?has_content>
                <p class="ev-card-description" data-slot="card-description">${subtitle}</p>
            </#if>
            <#if displayRequiredFields>
                <p class="ev-card-description"><span class="ev-required">*</span> ${msg("requiredFields")}</p>
            </#if>
        </header>

        <div id="kc-content" class="ev-card-content" data-slot="card-content">
            <#-- Les actions lancées par l'application n'affichent pas l'avertissement
                 « action à terminer » pendant la connexion (comme le thème de base) -->
            <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                <@alert type=message.type text=kcSanitize(message.summary)/>
            </#if>

            <#nested "form">

            <#if displayInfo>
                <div id="kc-info" class="${properties.kcSignUpClass!}">
                    <#nested "info">
                </div>
            </#if>
        </div>
    </div>
</main>
</body>
</html>
</#macro>

<#--
  Alert de shadcn (variante destructive pour les erreurs). text est déjà nettoyé
  (kcSanitize) par l'appelant.
-->
<#macro alert type text id="">
    <div<#if id?has_content> id="${id}"</#if> class="${properties.kcAlertClass!} ev-alert-${type}" role="<#if type = 'error' || type = 'warning'>alert<#else>status</#if>" data-slot="alert">
        <#if type = 'success'><i class="${properties.kcFeedbackSuccessIcon!}" aria-hidden="true"></i>
        <#elseif type = 'warning'><i class="${properties.kcFeedbackWarningIcon!}" aria-hidden="true"></i>
        <#elseif type = 'error'><i class="${properties.kcFeedbackErrorIcon!}" aria-hidden="true"></i>
        <#else><i class="${properties.kcFeedbackInfoIcon!}" aria-hidden="true"></i></#if>
        <div class="${properties.kcAlertTitleClass!}" data-slot="alert-description">${text?no_esc}</div>
    </div>
</#macro>
