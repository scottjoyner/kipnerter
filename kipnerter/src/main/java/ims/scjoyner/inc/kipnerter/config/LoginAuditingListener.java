package ims.scjoyner.inc.kipnerter.config;

import org.springframework.context.ApplicationEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authentication.event.AbstractAuthenticationFailureEvent;
import org.springframework.security.authentication.event.InteractiveAuthenticationSuccessEvent;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.web.authentication.WebAuthenticationDetails;
import org.springframework.stereotype.Component;

import ims.scjoyner.inc.kipnerter.models.enums.TransactionType;
import ims.scjoyner.inc.kipnerter.models.persistent.LoginBan;
import ims.scjoyner.inc.kipnerter.models.persistent.LoginLockout;
import ims.scjoyner.inc.kipnerter.models.persistent.LoginAttempt;
import ims.scjoyner.inc.kipnerter.models.persistent.User;
import ims.scjoyner.inc.kipnerter.utils.LoggerUtil;

/**
 * Listens for AuthenticationEvents to Log them and to clear FaieldAttempts on
 * successful authentication.
 *
 * @author Kai Presler-Marshall
 *
 */
@Component
public class LoginAuditingListener implements ApplicationListener<ApplicationEvent> {
    @Override
    public void onApplicationEvent ( final ApplicationEvent event ) {
        if ( event instanceof InteractiveAuthenticationSuccessEvent ) {
            final InteractiveAuthenticationSuccessEvent authEvent = (InteractiveAuthenticationSuccessEvent) event;
            final Authentication authentication = authEvent.getAuthentication();
            final UserDetails details = (UserDetails) authentication.getPrincipal();
            final UsernamePasswordAuthenticationToken source = (UsernamePasswordAuthenticationToken) authEvent
                    .getSource();
            final WebAuthenticationDetails det = (WebAuthenticationDetails) source.getDetails();

            // Clear login attempts for this User and this IP. if not IP banned.
            // If IP lockout or banned, this is still called, but the redirect
            // invalidates the credentials if they happen to be correct (and
            // bypassed the lockout page via a direct API call).
            final String addr = det.getRemoteAddress();
            if ( !LoginLockout.isIPLocked( addr ) && !LoginBan.isIPBanned( addr ) ) {
                LoginAttempt.clearIP( addr );
                LoginAttempt.clearUser( User.getByName( details.getUsername() ) );
                LoggerUtil.log( TransactionType.LOGIN_SUCCESS, details.getUsername() );
            }

        }

        if ( event instanceof AbstractAuthenticationFailureEvent ) {
            final AbstractAuthenticationFailureEvent authEvent = (AbstractAuthenticationFailureEvent) event;
            final Authentication authentication = authEvent.getAuthentication();
            LoggerUtil.log( TransactionType.LOGIN_FAILURE, authentication.getPrincipal().toString() );
        }
    }
}
