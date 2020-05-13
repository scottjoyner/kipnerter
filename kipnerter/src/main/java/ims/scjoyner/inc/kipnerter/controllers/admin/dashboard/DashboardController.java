package ims.scjoyner.inc.kipnerter.controllers.admin.dashboard;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * Dashboard Controller
 * 
 * @author scottjoyner
 *
 */
@Controller
public class DashboardController {
	/**
     * View Dashboard
     *
     * @param model
     *            data for front end
     * @return mapping
     */
    @RequestMapping ( value = "admin/dashboard" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String manageUser ( final Model model ) {
        return "/admin/dashboard/index";
    }
}
