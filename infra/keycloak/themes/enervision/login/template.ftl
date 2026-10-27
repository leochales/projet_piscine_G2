<#--
  Mise en page commune à toutes les pages de connexion du realm (connexion, mot de passe
  oublié, erreur...) : la marque EnerVision, une Card de shadcn et le pied de page.
  Même macro et mêmes sections que le template.ftl du thème de base, que les autres pages
  appellent ; « subtitle » en plus, pour le sous-titre de la carte (login.ftl).
-->
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" lang="${lang}"<#if realm.internationalizationEnabled> dir="${(locale.rtl)?then('rtl','ltr')}"</#if>>

<head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <#if properties.meta?has_content>
        <#list properties.meta?split(' ') as meta>
            <meta name="${meta?split('==')[0]}" content="${meta?split('==')[1]}"/>
        </#list>
    </#if>
    <title>${msg("loginTitle",(realm.displayName!''))}</title>
    <link rel="icon" href="${url.resourcesPath}/img/favicon.ico" />
    <#-- Même clé et même règle que front/index.html (le front est à la même adresse, donc
         même localStorage) : le thème choisi dans l'application, sinon celui du système -->
    <script>
        try {
            var theme = localStorage.getItem('enervision-theme')
            if (theme === 'dark' || ((!theme || theme === 'auto') && matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.classList.add('dark')
            } else {
                document.documentElement.classList.add('light')
            }
        } catch (e) {}
    </script>
    <#if properties.stylesCommon?has_content>
        <#list properties.stylesCommon?split(' ') as style>
            <link href="${url.resourcesCommonPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if properties.styles?has_content>
        <#list properties.styles?split(' ') as style>
            <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if properties.scripts?has_content>
        <#list properties.scripts?split(' ') as script>
            <script src="${url.resourcesPath}/${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="importmap">
        {
            "imports": {
                "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"
            }
        }
    </script>
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <#-- Scripts du thème de base : session ouverte dans un autre onglet, liens à usage unique -->
    <script type="module">
        import { startSessionPolling } from "${url.resourcesPath}/js/authChecker.js";

        startSessionPolling(
            "${url.ssoLoginInOtherTabsUrl?no_esc}"
        );
    </script>
    <script type="module">
        document.addEventListener("click", (event) => {
            const link = event.target.closest("a[data-once-link]");

            if (!link) {
                return;
            }

            if (link.getAttribute("aria-disabled") === "true") {
                event.preventDefault();
                return;
            }

            const { disabledClass } = link.dataset;

            if (disabledClass) {
                link.classList.add(...disabledClass.trim().split(/\s+/));
            }

            link.setAttribute("role", "link");
            link.setAttribute("aria-disabled", "true");
        });
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

<body class="${properties.kcBodyClass!} ${bodyClass}" data-page-id="login-${pageId}">
<main class="${properties.kcLoginClass!}">
    <div id="kc-header" class="${properties.kcHeaderClass!}">${kcSanitize(msg("loginTitleHtml",(realm.displayNameHtml!'')))?no_esc}</div>

    <div class="${properties.kcFormCardClass!}" data-slot="card">
        <header class="${properties.kcFormHeaderClass!}" data-slot="card-header">
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

            <#if auth?has_content && auth.showTryAnotherWayLink()>
                <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
                    <input type="hidden" name="tryAnotherWay" value="on"/>
                    <a href="#" id="try-another-way" class="ev-link"
                       onclick="document.forms['kc-select-try-another-way-form'].requestSubmit();return false;">${msg("doTryAnotherWay")}</a>
                </form>
            </#if>

            <#nested "socialProviders">

            <#if displayInfo>
                <div id="kc-info" class="${properties.kcSignUpClass!}">
                    <#nested "info">
                </div>
            </#if>
        </div>
    </div>

    <footer class="ev-footer">
        <span>&copy; ${.now?string("yyyy")} EnerVision</span>
        <#if realm.internationalizationEnabled && locale.supported?size gt 1>
            <nav class="ev-locales" aria-label="${msg("languages")}">
                <#list locale.supported as l>
                    <a href="${l.url}" class="ev-link" lang="${l.languageTag}"<#if l.languageTag == locale.currentLanguageTag> aria-current="true"</#if>>${l.languageTag?upper_case}</a>
                </#list>
            </nav>
        </#if>
    </footer>
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
