package ims.scjoyner.inc.kipnerter.controllers;

import java.util.List;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.servlet.view.RedirectView;

@Controller
public class DefaultController {

//    /**
//     * This controller is used to redirect the authenticated user to the
//     * appropriate landing screen based on their role.
//     *
//     * @param model
//     *            The data from the front end
//     * @return The page to be displayed to the user
//     */
//    @RequestMapping ( value = "/" )
//    public RedirectView index ( final Model model ) {
//        final Authentication auth = SecurityContextHolder.getContext().getAuthentication();
//        final List< ? extends GrantedAuthority> auths = (List< ? extends GrantedAuthority>) auth.getAuthorities();
//        final GrantedAuthority ga = auths.get( 0 );
//        return new RedirectView( ims.scjoyner.inc.kipnerter.models.enums.Role.valueOf( ga.toString() ).getLanding() );
//    }
//    
    /**
     * Add or delete user
     *
     * @param model
     *            data for front end
     * @return mapping
     */
    @RequestMapping ( value = "/" )
    public String manageUser ( final Model model ) {
        return "/home";
    }
}
